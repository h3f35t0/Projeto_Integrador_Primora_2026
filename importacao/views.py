import logging

import pandas as pd
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Q, TextField
from django.db.models.functions import Cast
from django.shortcuts import redirect, render, get_object_or_404
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from django.utils.text import get_valid_filename

from .forms import CadastroUsuarioForm, ExcelUploadForm
from .models import ClienteConsolidado, ImportacaoArquivo, RegistroImportado
from .services import salvar_linha

logger = logging.getLogger(__name__)


def home(request):
    if request.user.is_authenticated:
        return redirect("importacao:upload_excel")
    return redirect("login")


def ler_csv(arquivo):
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            arquivo.seek(0)
            return pd.read_csv(arquivo, sep=";", encoding=encoding, dtype=str, keep_default_na=False)
        except UnicodeDecodeError:
            continue
    raise ValueError("Não foi possível identificar a codificação do CSV.")


@login_required
def upload_excel(request):
    contexto = {"form": ExcelUploadForm()}
    if request.method == "POST":
        form = ExcelUploadForm(request.POST, request.FILES)
        contexto["form"] = form
        if form.is_valid():
            arquivo = form.cleaned_data["arquivo"]
            try:
                arquivo.seek(0)
                if arquivo.name.lower().endswith(".csv"):
                    planilha = ler_csv(arquivo)
                else:
                    planilha = pd.read_excel(arquivo, engine="openpyxl", dtype=str).fillna("")

                if planilha.empty:
                    messages.warning(request, "O arquivo foi lido, mas não contém registros.")
                else:
                    # Cabeçalhos são preservados; bairro_informado e cep são os campos usados nas regras.
                    colunas_obrigatorias = {"bairro_informado", "cep"}
                    faltantes = colunas_obrigatorias - set(planilha.columns)
                    if faltantes:
                        raise ValueError("Colunas obrigatórias ausentes: " + ", ".join(sorted(faltantes)))

                    # Guarda uma cópia do arquivo original para consulta e download posterior.
                    nome_seguro = get_valid_filename(arquivo.name)
                    caminho_arquivo = default_storage.save(
                        f"importacoes/{nome_seguro}", arquivo
                    )

                    with transaction.atomic():
                        lote = ImportacaoArquivo.objects.create(
                            nome_arquivo=arquivo.name,
                            usuario=request.user,
                            total_registros=len(planilha),
                            observacoes=[{"arquivo_salvo": caminho_arquivo}],
                        )
                        for indice, linha in enumerate(planilha.to_dict(orient="records"), start=2):
                            dados = {str(k): ("" if pd.isna(v) else str(v)) for k, v in linha.items()}
                            salvar_linha(lote, indice, dados)

                        registros = lote.registros.all()
                        lote.total_cep_ausente = registros.filter(status_cep="AUSENTE").count()
                        lote.total_cep_invalido = registros.filter(status_cep="INVALIDO").count()
                        lote.total_conflitos = registros.filter(status_conferencia="CONFLITO").count()
                        guara = registros.filter(bairro_canonico="Guará")
                        guara_com_cep_verificado = guara.filter(status_conferencia="COMPATIVEL").count()
                        if guara.exists() and not guara_com_cep_verificado:
                            lote.observacoes.append("GRUPO_GUARA_SEM_CEP_CONFIAVEL_NA_AMOSTRA")
                        lote.save()

                    messages.success(request, f"Importação concluída: {lote.total_registros} registros processados.")
                    contexto.update({
                        "lote": lote,
                        "registros": lote.registros.all(),
                        "total_cep_ausente": lote.total_cep_ausente,
                        "total_cep_invalido": lote.total_cep_invalido,
                        "total_conflitos": lote.total_conflitos,
                        "alertas_lote": lote.observacoes,
                        "campos_originais": list(planilha.columns),
                        "total_api_consultada": registros.filter(api_status="CONSULTADO").count(),
                        "total_api_indisponivel": registros.filter(api_status="INDISPONIVEL").count(),
                    })
            except Exception as erro:
                logger.exception("Falha ao processar arquivo enviado")
                messages.error(request, f"Não foi possível processar o arquivo: {erro}")
    return render(request, "importacao/upload.html", contexto)


def registro_tem_erro_vermelho(registro):
    """Replica os critérios de erro vermelho da tabela de dados originais."""
    return (
        registro.email_status == "INVALIDO"
        or registro.cnpj_status == "INVALIDO"
        or registro.telefone_status == "INVALIDO"
        or registro.data_cadastro_status == "INVALIDA"
        or registro.status_cep in ("AUSENTE", "INVALIDO")
        or registro.status_conferencia == "CONFLITO"
        or not registro.bairro_canonico
    )


def montar_dados_ajustados(registro):
    """Mantém todos os campos e substitui apenas os que possuem valor normalizado."""
    ajustados = dict(registro.dados_originais or {})
    if "bairro_informado" in ajustados and registro.bairro_normalizado:
        ajustados["bairro_informado"] = registro.bairro_normalizado
    if "cep" in ajustados and registro.cep_normalizado:
        cep = registro.cep_normalizado
        ajustados["cep"] = f"{cep[:5]}-{cep[5:]}" if len(cep) == 8 else cep
    if "cnpj" in ajustados and registro.cnpj_normalizado:
        ajustados["cnpj"] = registro.cnpj_normalizado
    if "telefone" in ajustados and registro.telefone_normalizado:
        ajustados["telefone"] = registro.telefone_normalizado
    if "data_cadastro" in ajustados and registro.data_cadastro_normalizada:
        ajustados["data_cadastro"] = registro.data_cadastro_normalizada.strftime("%d/%m/%Y")
    return ajustados


@login_required
def salvar_lote(request, lote_id):
    if request.method != "POST":
        return redirect("importacao:upload_excel")

    lote = ImportacaoArquivo.objects.filter(pk=lote_id, usuario=request.user).first()
    if lote is None:
        messages.error(request, "Importação não encontrada ou sem permissão para salvá-la.")
        return redirect("importacao:upload_excel")

    criados = 0
    atualizados = 0
    with transaction.atomic():
        for registro in lote.registros.all():
            dados = {
                "dados_originais": registro.dados_originais or {},
                "dados_ajustados": montar_dados_ajustados(registro),
                "usuario_gravacao": request.user,
                "isvalido": not registro_tem_erro_vermelho(registro),
            }
            _, created = ClienteConsolidado.objects.update_or_create(
                registro_origem=registro, defaults=dados
            )
            if created:
                criados += 1
            else:
                atualizados += 1

    messages.success(
        request,
        f"Gravação concluída: {criados} novos registros e {atualizados} atualizados. "
        "Alertas laranja não tornam o registro inválido.",
    )
    return redirect("importacao:upload_excel")


@login_required
def listar_consolidados(request):
    """Lista os registros persistidos com pesquisa e filtros."""
    registros = ClienteConsolidado.objects.select_related(
        "registro_origem", "registro_origem__importacao"
    ).all()

    termo = request.GET.get("q", "").strip()
    validade = request.GET.get("isvalido", "").strip()

    if termo:
        registros = registros.annotate(
            originais_texto=Cast("dados_originais", output_field=TextField()),
            ajustados_texto=Cast("dados_ajustados", output_field=TextField()),
        ).filter(
            Q(originais_texto__icontains=termo)
            | Q(ajustados_texto__icontains=termo)
            | Q(registro_origem__bairro_original__icontains=termo)
            | Q(registro_origem__bairro_normalizado__icontains=termo)
            | Q(registro_origem__api_bairro__icontains=termo)
            | Q(registro_origem__cep_original__icontains=termo)
            | Q(registro_origem__cnpj_normalizado__icontains=termo)
            | Q(registro_origem__telefone_normalizado__icontains=termo)
            | Q(registro_origem__importacao__nome_arquivo__icontains=termo)
        ).distinct()

    if validade == "true":
        registros = registros.filter(isvalido=True)
    elif validade == "false":
        registros = registros.filter(isvalido=False)

    paginator = Paginator(registros, 25)
    pagina = paginator.get_page(request.GET.get("page"))
    importacoes = ImportacaoArquivo.objects.order_by("-criado_em")[:100]
    contexto = {
        "importacoes": importacoes,
        "pagina": pagina,
        "termo": termo,
        "validade": validade,
        "total_registros": ClienteConsolidado.objects.count(),
        "total_validos": ClienteConsolidado.objects.filter(isvalido=True).count(),
        "total_invalidos": ClienteConsolidado.objects.filter(isvalido=False).count(),
    }
    return render(request, "importacao/consolidados.html", contexto)


@login_required
def baixar_planilha_importada(request, lote_id):
    """Disponibiliza o arquivo original de uma importação salva."""
    lote = get_object_or_404(ImportacaoArquivo, pk=lote_id)
    caminho = ""
    for observacao in lote.observacoes or []:
        if isinstance(observacao, dict) and observacao.get("arquivo_salvo"):
            caminho = observacao["arquivo_salvo"]
            break
    if not caminho or not default_storage.exists(caminho):
        raise Http404("Arquivo original não encontrado.")
    try:
        arquivo = default_storage.open(caminho, "rb")
    except OSError:
        raise Http404("Não foi possível abrir o arquivo original.")
    return FileResponse(arquivo, as_attachment=True, filename=lote.nome_arquivo)


@login_required
def cadastrar_usuario(request):
    """Cria usuários e apresenta a administração básica das contas."""
    if not request.user.is_staff:
        raise PermissionDenied("Somente administradores podem gerenciar usuários.")

    if request.method == "POST":
        form = CadastroUsuarioForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            messages.success(request, f"Usuário '{usuario.username}' cadastrado com sucesso.")
            return redirect("importacao:cadastrar_usuario")
    else:
        form = CadastroUsuarioForm()

    usuarios = User.objects.all().order_by("username")
    return render(request, "importacao/cadastrar_usuario.html", {
        "form": form,
        "usuarios": usuarios,
    })


@login_required
def alternar_status_usuario(request, usuario_id):
    if not request.user.is_staff:
        raise PermissionDenied("Somente administradores podem gerenciar usuários.")
    if request.method != "POST":
        return redirect("importacao:cadastrar_usuario")

    usuario = User.objects.filter(pk=usuario_id).first()
    if usuario is None:
        messages.error(request, "Usuário não encontrado.")
    elif usuario.is_superuser:
        messages.error(request, "Não é permitido desabilitar ou habilitar uma conta de superusuário por esta tela.")
    elif usuario.pk == request.user.pk:
        messages.error(request, "Você não pode desabilitar sua própria conta.")
    else:
        usuario.is_active = not usuario.is_active
        usuario.save(update_fields=["is_active"])
        estado = "habilitado" if usuario.is_active else "desabilitado"
        messages.success(request, f"Usuário '{usuario.username}' {estado} com sucesso.")
    return redirect("importacao:cadastrar_usuario")


@login_required
def resetar_senha_usuario(request, usuario_id):
    if not request.user.is_staff:
        raise PermissionDenied("Somente administradores podem gerenciar usuários.")
    if request.method != "POST":
        return redirect("importacao:cadastrar_usuario")

    usuario = User.objects.filter(pk=usuario_id).first()
    if usuario is None:
        messages.error(request, "Usuário não encontrado.")
    elif usuario.is_superuser:
        messages.error(request, "Não é permitido resetar a senha de um superusuário por esta tela.")
    else:
        senha_temporaria = get_random_string(16)
        usuario.set_password(senha_temporaria)
        usuario.save(update_fields=["password"])
        messages.success(
            request,
            f"Senha de '{usuario.username}' redefinida. Senha temporária: {senha_temporaria}. "
            "Copie e entregue ao usuário por um canal seguro.",
        )
    return redirect("importacao:cadastrar_usuario")
