from django.shortcuts import render, redirect
from django.contrib import messages, auth
from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib.sites.shortcuts import get_current_site
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.core.mail import EmailMessage
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string

from .forms import RegistrationForm, LoginForm
from .models import Account


def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)

        if form.is_valid():
            # Your custom model uses email as USERNAME_FIELD
            first_name = form.cleaned_data['first_name']
            last_name = form.cleaned_data['last_name']
            email = form.cleaned_data['email']
            phone_number = form.cleaned_data['phone_number']
            password = form.cleaned_data['password']

            # Create username automatically from email (safe approach)
            username = email.split('@')[0]

            user = Account.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
            )

            user.is_active = False
            user.save()

            # messages.success(request, 'Registration successful. Please log in.')
            # build activation link
            current_site =get_current_site(request)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            activation_path = reverse('activate',kwargs={'uidb64':uid, 'token': token})
            activation_url = f"{request.scheme}://{current_site.domain} {activation_path}"
            subject = 'Activate you account'
            body = (
                f"Hi {user.first_name or user.username}, \n\n"
                "Thanks for registering. Please click the link below to activate your account: \n\n"
                f"{activation_url}\n\n" 
                "if you didn't create this account, you can ignore this email. \n"
            )
            email_message = EmailMessage(
                subject=subject, 
                body=body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL',None),
                to=[user.email],
            )
            email_message.send(fail_silently=False)
            messages.success(request, 'Registration successful. Please check your email to activate your account before logging in')
            return redirect('login')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = RegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})

def activate(request, uidb64, token):
    '''Activate a user account via emailed token'''
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = Account.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, Account.DoesNotExist):
        user = None
    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        messages.success(request, 'Your account has been activated. You can now log in. ')
        return redirect('login')
    messages.error(request, 'Activation link is invalid or has expired. ')
    return redirect('register')


# Resend activation email view
def resend_activation_email(request):
    """Resend account activation email if the user did not receive it."""
    if request.method == 'POST':
        email = request.POST.get('email')

        try:
            user = Account.objects.get(email=email)
        except Account.DoesNotExist:
            messages.error(request, 'Account with this email does not exist.')
            return redirect('resend_activation')

        if user.is_active:
            messages.info(request, 'Your account is already activated. Please log in.')
            return redirect('login')

        # rebuild activation link
        current_site = get_current_site(request)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        activation_path = reverse('activate', kwargs={'uidb64': uid, 'token': token})
        activation_url = f"{request.scheme}://{current_site.domain}{activation_path}"

        subject = 'Resend Activation Email'
        body = (
            f"Hi {user.first_name or user.username},\n\n"
            "Please click the link below to activate your account:\n\n"
            f"{activation_url}\n\n"
            "If you did not create this account, you can ignore this email.\n"
        )

        email_message = EmailMessage(
            subject=subject,
            body=body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            to=[user.email],
        )
        email_message.send(fail_silently=False)

        messages.success(request, 'A new activation email has been sent to your email address.')
        return redirect('login')

    return render(request, 'accounts/resend_activation.html')

def login_view(request):
    form = LoginForm()

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']

            user = authenticate(request, email=email, password=password)
            if user is not None:
                auth_login(request, user)

                # redirect back to the page user wanted
                next_url = request.GET.get('next')
                if next_url:
                    return redirect(next_url)

                return redirect('home')
            else:
                messages.error(request, 'Invalid email or password.')

    return render(request, 'accounts/login.html', {'form': form})

@login_required(login_url='login')
def logout_view(request):
    auth.logout(request)
    messages.info(request, 'You are logged out.')
    return redirect('login')

def forgotPassword(request):
    if request.method == 'POST':
        email = request.POST['email']
        if Account.objects.filter(email=email).exists():
            user = Account.objects.get(email__exact=email)

            current_site = get_current_site(request)
            mail_subject = "Reset your password"
            message = render_to_string('accounts/reset_password_email.html', {
                'user':user, 
                'domain': current_site.domain,
                'uid':urlsafe_base64_encode(force_bytes(user.pk)),
                'token': default_token_generator.make_token(user),
            })
            to_email = email
            send_email = EmailMessage(mail_subject, message, to=[to_email])
            send_email.content_subtype = 'html'
            send_email.send()

            messages.success(request, 'Password reset email has been sent to you email')
            return redirect('login')
        else:
            messages.error(request, 'Account does not exist!')
            return redirect('forgotPassword')
    return render(request, 'accounts/forgotPassword.html')

def resetpassword_validate(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = Account._default_manager.get(pk=uid)
    except(TypeError, ValueError, OverflowError, Account.DoesNotExist):
        user=None

    if user is not None and default_token_generator.check_token(user, token):
        request.session['uid'] = uid
        messages.success(request, 'Please reset your password')
        return redirect('resetPassword')
    else:
        messages.error(request, 'The link has been expired!')
        return redirect('login')
    
def resetPassword(request): 
    if request.method == 'POST':
        password = request.POST['password']
        confirm_password = request.POST['confirm_password']

        if password == confirm_password:
            uid = request.session.get('uid')
            user = Account.objects.get(pk=uid)
            user.set_password(password)
            user.save()
            messages.success(request, 'Password reset successfull')
            return redirect('login')
        else:
            messages.error(request, 'Passwords did not match!')
            return redirect('resetPassword')
    else:
        return render(request,'accounts/resetPassword.html')