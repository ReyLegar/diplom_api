import datetime
import uuid

from rest_framework import status
from .forms import CreditConfirmationForm
from api.models import CustomUser, CreditApplication, Credit
from api.serializers import CustomTokenObtainPairSerializer, CreditApplicationSerializer

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication


def admin_authorization_page(request):
    if request.method == 'POST':
        phone_number = request.POST['phone_number']
        password = request.POST['password']
        personal_code = request.POST['personal_code']
        try:
            admin_user = CustomUser.objects.get(phone_number=phone_number)
            if admin_user.password == password and admin_user.personal_code == personal_code:
                request.session['admin_user_id'] = admin_user.id
                request.session['admin_user_name'] = admin_user.first_name + ' ' + admin_user.last_name
                return redirect('admin_home')
            else:
                error_message = 'Неверный номер телефона, пароль или персональный код'
                return render(request, 'admin_authorization.html', {'error_message': error_message})
        except CustomUser.DoesNotExist:
            error_message = 'Неверный номер телефона, пароль или персональный код'
        return render(request, 'admin_authorization.html', {'error_message': error_message})

    return render(request, 'admin_authorization.html')


def admin_home(request):
    if 'admin_user_id' not in request.session:
        error_message = 'Вы не авторизованы'
        return render(request, 'admin_authorization.html', {'error_message': error_message})

    admin_user = CustomUser.objects.get(id=request.session['admin_user_id'])
    admin_user_name = admin_user.first_name + ' ' + admin_user.last_name
    users = CustomUser.objects.all()
    return render(request, 'admin_home.html', {'admin_user_name': admin_user_name, 'users': users})


def create_user(request):
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        patronymic = request.POST.get('patronymic')
        balance = request.POST.get('balance')
        document_image = request.FILES.get('document_image')
        password = request.POST.get('password')
        
        username = str(uuid.uuid4())
        
        user = CustomUser.objects.create(
            username=username,
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
            patronymic=patronymic,
            balance=balance,
            document_image=document_image,
            password=password,
        )
        
        return render(request, 'admin_home.html')
    else:
        return render(request, 'create_user.html')
    

def user_info(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id)
    return render(request, 'user_info.html', {'user': user})


def credit_applications(request):
    credit_applications = CreditApplication.objects.all()
    return render(request, 'credit_applications.html', {'credit_applications': credit_applications})


class CustomTokenObtainPairView(APIView):
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)
    

class UserInfoView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        data = {
            'phone_number': user.phone_number,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'patronymic': user.patronymic,
            'balance': user.balance,
            'document_image': user.document_image.url if user.document_image else None,
        }
        return Response(data)
    

class CreateCreditApplicationView(APIView):
    def post(self, request):
        serializer = CreditApplicationSerializer(data=request.data)
        if serializer.is_valid():
            credit_application = serializer.save(user=request.user)
            return Response({'id': credit_application.id}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def active_credits(request):
    active_credits = Credit.objects.all().order_by('payment_dates')
    return render(request, 'active_credits.html', {'active_credits': active_credits})


def confirm_credit(request, credit_application_id):
    # Получаем заявку на кредит по переданному id
    try:
        credit_application = CreditApplication.objects.get(id=credit_application_id)
    except CreditApplication.DoesNotExist:
        return HttpResponseBadRequest('Неправильный id заявки на кредит')

    # Проверяем, что заявка еще не подтверждена или отклонена
    if credit_application.status != CreditApplication.PENDING:
        return HttpResponseBadRequest('Заявка на кредит уже подтверждена или отклонена')

    # Если метод запроса POST, обрабатываем форму подтверждения
    if request.method == 'POST':
        form = CreditConfirmationForm(request.POST, request.FILES)
        if form.is_valid():

            # Получаем данные из формы
            payment_period = form.cleaned_data['term']
            interest_rate = form.cleaned_data['interest_rate']

            payment_document = form.cleaned_data['document']

            # Рассчитываем платежи
            payment_dates = calculate_payment_dates(payment_period, interest_rate, credit_application.amount)

            # Создаем новый кредит и сохраняем его в базе данных
            new_credit = Credit.objects.create(
                user=credit_application.user,
                amount=credit_application.amount,
                payment_dates=','.join(payment_dates),
                image=payment_document
            )

            # Меняем статус заявки на кредит на "Одобрена"
            credit_application.status = CreditApplication.APPROVED
            credit_application.save()

            return HttpResponseRedirect(reverse('credit_applications'))

    # Если метод GET, просто отображаем форму
    else:
        form = CreditConfirmationForm()

    context = {
        'form': form,
        'credit_application': credit_application
    }
    return render(request, 'confirm_credit_application.html', context)


def calculate_payment_dates(payment_period, interest_rate, amount):
    monthly_interest_rate = interest_rate / 12

    num_payments = payment_period

    monthly_payment = amount * monthly_interest_rate / (1 - (1 + monthly_interest_rate) ** (-num_payments))

    payment_dates = []
    date = datetime.date.today() + datetime.timedelta(days=30)
    for i in range(num_payments):
        payment_dates.append(date.strftime('%d.%m.%Y'))
        date += datetime.timedelta(days=30)

    return payment_dates

class CreditListView(APIView):

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        credits = Credit.objects.filter(user=user)
        active_credits = []
        for credit in credits:
            payment_dates = credit.payment_dates.split(',')
            last_payment_date = datetime.datetime.strptime(payment_dates[-1], '%d.%m.%Y').date()
            active_credits.append({
                'id': credit.id,
                'amount': credit.amount,
                'payment_dates': payment_dates,
                'image_url': request.build_absolute_uri(credit.image.url),
            })
        return Response(active_credits)
