from django import forms
from django.contrib.auth.models import User

from .models import Comercio, Producto


class RegistroForm(forms.Form):
    nombre_comercio = forms.CharField(label="Nombre de tu comercio", max_length=100)
    tipo_comercio = forms.ChoiceField(label="Tipo de comercio", choices=Comercio.TIPOS)
    region = forms.CharField(label="Región", max_length=60, initial="Valparaíso")
    usuario = forms.CharField(label="Nombre de usuario", max_length=30)
    email = forms.EmailField(label="Correo electrónico")
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput, min_length=6)
    password2 = forms.CharField(label="Repite la contraseña", widget=forms.PasswordInput)

    def clean_usuario(self):
        usuario = self.cleaned_data["usuario"].strip()
        if User.objects.filter(username__iexact=usuario).exists():
            raise forms.ValidationError("Ese nombre de usuario ya existe. Elige otro.")
        return usuario

    def clean(self):
        datos = super().clean()
        if datos.get("password1") and datos.get("password1") != datos.get("password2"):
            self.add_error("password2", "Las contraseñas no coinciden.")
        return datos


class VendedorForm(forms.Form):
    usuario = forms.CharField(label="Nombre de usuario", max_length=30)
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput, min_length=6)

    def clean_usuario(self):
        usuario = self.cleaned_data["usuario"].strip()
        if User.objects.filter(username__iexact=usuario).exists():
            raise forms.ValidationError("Ese nombre de usuario ya existe. Elige otro.")
        return usuario


class ComercioForm(forms.ModelForm):
    class Meta:
        model = Comercio
        fields = ["nombre", "rut", "tipo_comercio", "region", "telefono", "email", "logo"]


class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = ["sku", "nombre", "descripcion", "precio", "costo", "stock_actual", "stock_minimo", "stock_objetivo", "activo"]

    def __init__(self, *args, comercio=None, editando=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.comercio = comercio
        self.fields["sku"].required = False
        self.fields["sku"].help_text = "Si lo dejas vacío se genera solo."
        if editando:   # el stock solo se cambia con ajustes o compras, para que quede registrado
            del self.fields["stock_actual"]
        else:
            del self.fields["activo"]

    def clean_sku(self):
        sku = self.cleaned_data.get("sku", "").strip()
        if sku:
            otros = Producto.objects.filter(comercio=self.comercio, sku__iexact=sku)
            if self.instance.pk:
                otros = otros.exclude(pk=self.instance.pk)
            if otros.exists():
                raise forms.ValidationError("Ya existe un producto con ese código.")
        return sku


class AjusteForm(forms.Form):
    tipo = forms.ChoiceField(label="Tipo", choices=[("merma", "Merma (producto perdido o vencido)"),
                                                    ("ajuste", "Ajuste (stock contado en la tienda)")])
    cantidad = forms.IntegerField(label="Cantidad", min_value=0)
    nota = forms.CharField(label="Motivo", max_length=200, required=False)


class CargaForm(forms.Form):
    tipo = forms.ChoiceField(label="¿Qué vas a subir?", choices=[
        ("factura", "Factura de compra (XML o PDF digital)"),
        ("catalogo", "Catálogo anterior (Excel o CSV)")])
    archivo = forms.FileField(label="Archivo")
