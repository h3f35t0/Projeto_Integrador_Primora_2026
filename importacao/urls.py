from django.urls import path
from . import views

app_name = "importacao"
urlpatterns = [
    path("upload/", views.upload_excel, name="upload_excel"),
    path("consolidados/", views.listar_consolidados, name="listar_consolidados"),
    path("importacao/<int:lote_id>/baixar/", views.baixar_planilha_importada, name="baixar_planilha_importada"),
    path("usuarios/novo/", views.cadastrar_usuario, name="cadastrar_usuario"),
    path("usuarios/<int:usuario_id>/status/", views.alternar_status_usuario, name="alternar_status_usuario"),
    path("usuarios/<int:usuario_id>/resetar-senha/", views.resetar_senha_usuario, name="resetar_senha_usuario"),
    path("lote/<int:lote_id>/salvar/", views.salvar_lote, name="salvar_lote"),
]
