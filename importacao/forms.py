from django import forms

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

class ExcelUploadForm(forms.Form):
    arquivo = forms.FileField(
        label="Arquivo Excel ou CSV",
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control",
            "accept": ".xlsx,.csv",
        }),
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        nome = arquivo.name.lower()

        if not (nome.endswith(".xlsx") or nome.endswith(".csv")):
            raise forms.ValidationError("Envie um arquivo .xlsx ou .csv.")

        if arquivo.size > MAX_UPLOAD_SIZE:
            raise forms.ValidationError("O arquivo deve ter no máximo 10 MB.")

        return arquivo

from django.contrib.auth import password_validation
from django.contrib.auth.models import User


class CadastroUsuarioForm(forms.Form):
    username = forms.CharField(
        label="Login",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "username"}),
    )
    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Este login já está cadastrado.")
        return username

    def clean_password(self):
        password = self.cleaned_data["password"]
        password_validation.validate_password(password)
        return password

    def save(self):
        return User.objects.create_user(
            username=self.cleaned_data["username"],
            password=self.cleaned_data["password"],
        )
