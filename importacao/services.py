import re
import unicodedata
from datetime import datetime
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from functools import lru_cache

import requests

from .models import ReferenciaCEP, RegistroImportado

ALIASES = {
    "AGUAS CLARAS": "Águas Claras",
    "AGUAS CLARA": "Águas Claras",
    "TAGUATINGA": "Taguatinga",
    "VICENTE PIRES": "Vicente Pires",
    "VTE PIRES": "Vicente Pires",
    "V PIRES": "Vicente Pires",
    "GUARA": "Guará",
}


def sem_acentos(valor):
    return "".join(c for c in unicodedata.normalize("NFKD", str(valor)) if not unicodedata.combining(c))


def chave_texto(valor):
    valor = sem_acentos(valor).upper().strip()
    valor = re.sub(r"\b(DF|DISTRITO FEDERAL)\b", " ", valor)
    valor = re.sub(r"[^A-Z0-9]+", " ", valor)
    return re.sub(r"\s+", " ", valor).strip()


def normalizar_bairro(valor):
    original = str(valor or "").strip()
    chave = chave_texto(original)
    if not chave:
        return {"normalizado": "", "canonico": "", "subdivisao": "", "observacoes": ["BAIRRO_AUSENTE"]}

    subdivisao = ""
    base = chave
    padroes = [
        (r"^(NORTE|SUL) AGUAS CLARAS$", "AGUAS CLARAS"),
        (r"^(AGUAS CLARAS) (NORTE|SUL)$", "AGUAS CLARAS"),
        (r"^(GUARA) (I|II|1|2)$", "GUARA"),
        (r"^(TAGUATINGA) (NORTE|SUL)$", "TAGUATINGA"),
    ]
    for pattern, canon_base in padroes:
        match = re.match(pattern, chave)
        if match:
            if canon_base == "AGUAS CLARAS":
                subdivisao = match.group(1) if match.group(1) in ("NORTE", "SUL") else match.group(2)
            elif canon_base == "GUARA":
                subdivisao = "I" if match.group(2) in ("I", "1") else "II"
            else:
                subdivisao = match.group(2)
            base = canon_base
            break

    # Exemplos como "Sul (Águas Claras)" são reduzidos à chave equivalente.
    canonico = ALIASES.get(base, "")
    observacoes = []
    if not canonico:
        observacoes.append("BAIRRO_NAO_RECONHECIDO_PARA_CANONICALIZACAO")
    if subdivisao:
        observacoes.append("SUBDIVISAO_PRESERVADA")
    return {
        "normalizado": chave,
        "canonico": canonico,
        "subdivisao": subdivisao,
        "observacoes": observacoes,
    }


def normalizar_cep(valor):
    original = str(valor or "").strip()
    if not original:
        return "", "AUSENTE"
    digitos = re.sub(r"\D", "", original)
    if len(digitos) != 8 or digitos == "00000000":
        return digitos, "INVALIDO"
    return digitos, "FORMATO_VALIDO"


@lru_cache(maxsize=4096)
def consultar_cep_api(cep):
    """
    Consulta dados reais em tempo de importação.
    Tenta ViaCEP primeiro e usa BrasilAPI como fallback.
    O cache evita repetir chamadas para CEPs duplicados no mesmo processo.
    """
    headers = {"Accept": "application/json", "User-Agent": "Django-ETL-QualidadeDados/1.0"}
    erros = []

    # ViaCEP
    try:
        response = requests.get(
            f"https://viacep.com.br/ws/{cep}/json/",
            headers=headers,
            timeout=(3, 6),
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("erro"):
            result = {
                "provedor": "ViaCEP",
                "status": "CONSULTADO",
                "bairro": data.get("bairro") or "",
                "cidade": data.get("localidade") or "",
                "uf": data.get("uf") or "",
                "logradouro": data.get("logradouro") or "",
                "resposta": data,
            }
            # Se ViaCEP não informa bairro, tenta BrasilAPI para obter dado complementar.
            if result["bairro"]:
                return result
        else:
            erros.append("ViaCEP: CEP não encontrado")
    except (requests.RequestException, ValueError) as exc:
        erros.append(f"ViaCEP: {type(exc).__name__}")

    # BrasilAPI (fallback ou complemento quando ViaCEP não retorna bairro)
    try:
        response = requests.get(
            f"https://brasilapi.com.br/api/cep/v2/{cep}",
            headers=headers,
            timeout=(3, 6),
        )
        response.raise_for_status()
        data = response.json()
        if data:
            return {
                "provedor": "BrasilAPI",
                "status": "CONSULTADO",
                "bairro": data.get("neighborhood") or data.get("bairro") or "",
                "cidade": data.get("city") or data.get("localidade") or "",
                "uf": data.get("state") or data.get("uf") or "",
                "logradouro": data.get("street") or data.get("logradouro") or "",
                "resposta": data,
            }
    except (requests.RequestException, ValueError) as exc:
        erros.append(f"BrasilAPI: {type(exc).__name__}")

    return {
        "provedor": "",
        "status": "NAO_ENCONTRADO" if any("não encontrado" in e for e in erros) else "INDISPONIVEL",
        "bairro": "",
        "cidade": "",
        "uf": "",
        "logradouro": "",
        "resposta": {"erros": erros},
    }



def validar_email(valor):
    original = str(valor or "").strip()
    if not original:
        return "AUSENTE", "E-mail não informado"
    try:
        validate_email(original)
        return "VALIDO", ""
    except ValidationError:
        return "INVALIDO", "Formato de e-mail inválido"


def validar_cnpj(valor):
    original = str(valor or "").strip()
    digitos = re.sub(r"\D", "", original)

    if not original:
        return "AUSENTE", "", "CNPJ não informado"

    if len(digitos) != 14:
        return (
            "FORMATO_INCORRETO",
            "",
            "CNPJ fora do formato esperado. São necessários 14 dígitos "
            "para aplicar a máscara 00.000.000/0000-00."
        )

    cnpj_formatado = (
        f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/"
        f"{digitos[8:12]}-{digitos[12:14]}"
    )

    if original != cnpj_formatado:
        return (
            "FORMATO_INCORRETO",
            cnpj_formatado,
            f"Atenção: o CNPJ está fora do formato esperado. "
            f"Será utilizado no formato {cnpj_formatado}."
        )

    # Não valida os dígitos verificadores; somente a máscara e 14 dígitos.
    return "VALIDO", cnpj_formatado, "Formato do CNPJ correto"

def validar_telefone(valor):
    original = str(valor or "").strip()
    if not original:
        return "AUSENTE", "", "Telefone não informado"

    digitos = re.sub(r"\D", "", original)

    # Aceita telefone brasileiro com DDD, com ou sem o código do país 55.
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos_nacionais = digitos[2:]
    elif len(digitos) in (10, 11):
        digitos_nacionais = digitos
    else:
        return (
            "INVALIDO",
            "",
            "Telefone não reconhecido. Utilize +55 DD XXXX-XXXX "
            "ou +55 DD XXXXX-XXXX."
        )

    ddd = digitos_nacionais[:2]
    numero = digitos_nacionais[2:]
    if len(numero) == 8:
        numero_formatado = f"{numero[:4]}-{numero[4:]}"
    else:
        numero_formatado = f"{numero[:5]}-{numero[5:]}"

    telefone_formatado = f"+55 {ddd} {numero_formatado}"

    if original == telefone_formatado:
        return "VALIDO", telefone_formatado, "Formato do telefone correto"

    return (
        "FORMATO_INCORRETO",
        telefone_formatado,
        f"Atenção: o telefone está fora do formato esperado. "
        f"Será utilizado como {telefone_formatado}."
    )

def validar_data_cadastro(valor):
    # Trata células vazias do CSV/Excel (None, NaN, NaT e texto em branco).
    if valor is None:
        return "AUSENTE", None, "Data de cadastro não informada: campo em branco"

    original = str(valor).strip()
    if not original or original.lower() in {"nan", "nat", "none", "null"}:
        return "AUSENTE", None, "Data de cadastro não informada: campo em branco"

    formatos = (
        "%d/%m/%Y",  # formato esperado
        "%Y-%m-%d",  # ISO
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%d.%m.%Y",
        "%m/%d/%Y",  # formato americano numérico
    )

    data = None
    for formato in formatos:
        try:
            data = datetime.strptime(original, formato).date()
            break
        except (ValueError, TypeError):
            continue

    # Reconhece meses escritos em inglês e português, por exemplo:
    # Jul 21, 2022; Dec 24, 2023; Feb 28, 2023; nov 19, 2021.
    if data is None:
        meses = {
            "jan": 1, "january": 1, "janeiro": 1,
            "feb": 2, "february": 2, "fev": 2, "fevereiro": 2,
            "mar": 3, "march": 3, "marco": 3, "março": 3,
            "apr": 4, "april": 4, "abr": 4, "abril": 4,
            "may": 5, "mai": 5, "maio": 5,
            "jun": 6, "june": 6, "junho": 6,
            "jul": 7, "july": 7, "julho": 7,
            "aug": 8, "august": 8, "ago": 8, "agosto": 8,
            "sep": 9, "sept": 9, "september": 9, "set": 9, "setembro": 9,
            "oct": 10, "october": 10, "out": 10, "outubro": 10,
            "nov": 11, "november": 11, "novembro": 11,
            "dec": 12, "december": 12, "dez": 12, "dezembro": 12,
        }
        correspondencia = re.fullmatch(
            r"([A-Za-zÀ-ÿ]+)\s+(\d{1,2}),?\s+(\d{4})",
            original,
            flags=re.IGNORECASE,
        )
        if correspondencia:
            nome_mes, dia, ano = correspondencia.groups()
            chave_mes = nome_mes.lower()
            numero_mes = meses.get(chave_mes)
            if numero_mes:
                try:
                    data = datetime(int(ano), numero_mes, int(dia)).date()
                except ValueError:
                    data = None

    if data is None:
        return "INVALIDA", None, (
            f"Data informada ({original}) inválida ou não reconhecida. "
            "Não será utilizada; informe uma data válida no formato DD/MM/YYYY."
        )

    data_formatada = data.strftime("%d/%m/%Y")
    if original == data_formatada:
        return "VALIDA", data, "Formato da data correto (DD/MM/YYYY)"

    return "CORRIGIDA", data, (
        f"Atenção: a data original ({original}) está em formato incorreto. "
        f"Será utilizada como {data_formatada} (DD/MM/YYYY)."
    )

def analisar_registro(dados):
    bairro = normalizar_bairro(dados.get("bairro_informado", ""))
    cep, status_cep = normalizar_cep(dados.get("cep", ""))
    observacoes = list(bairro["observacoes"])
    status_conferencia = "NAO_VERIFICADO"
    api = {
        "provedor": "",
        "status": "NAO_CONSULTADO",
        "bairro": "",
        "cidade": "",
        "uf": "",
        "logradouro": "",
        "resposta": {},
    }

    if status_cep == "AUSENTE":
        observacoes.append("CEP_AUSENTE")
    elif status_cep == "INVALIDO":
        observacoes.append("CEP_FORMATO_INVALIDO")
    elif status_cep == "FORMATO_VALIDO":
        api = consultar_cep_api(cep)

        if api["status"] == "CONSULTADO":
            if api["uf"] and api["uf"].upper() != "DF":
                status_conferencia = "CONFLITO"
                observacoes.append("CEP_API_RETORNOU_UF_DIFERENTE_DE_DF")
            elif not api["bairro"]:
                observacoes.append("API_NAO_RETORNOU_BAIRRO")
            else:
                bairro_api = normalizar_bairro(api["bairro"])
                if bairro["canonico"] and bairro_api["canonico"]:
                    if bairro["canonico"] == bairro_api["canonico"]:
                        status_conferencia = "COMPATIVEL"
                    else:
                        status_conferencia = "DIVERGENCIA_API"
                        observacoes.append("CEP_API_NAO_CORRESPONDE_AO_BAIRRO_INFORMADO")
                elif chave_texto(bairro["normalizado"]) == chave_texto(api["bairro"]):
                    status_conferencia = "COMPATIVEL"
                else:
                    status_conferencia = "NAO_VERIFICADO"
                    observacoes.append("BAIRRO_DA_API_EXIGE_REVISAO_MANUAL")
        else:
            observacoes.append("CONSULTA_API_CEP_NAO_CONFIRMADA")

        # A referência local é uma segunda fonte. Só é usada se API não confirmou comparação.
        if status_conferencia == "NAO_VERIFICADO":
            referencia = ReferenciaCEP.objects.filter(cep=cep, ativo=True).first()
            if referencia and bairro["canonico"]:
                if chave_texto(referencia.bairro_canonico) == chave_texto(bairro["canonico"]):
                    status_conferencia = "COMPATIVEL"
                else:
                    status_conferencia = "CONFLITO"
                    observacoes.append("CEP_NAO_CORRESPONDE_A_REFERENCIA_LOCAL")

    if not bairro["canonico"]:
        status_conferencia = "BAIRRO_NAO_IDENTIFICADO"

    email_status, email_observacao = validar_email(dados.get("email", ""))
    cnpj_status, cnpj_normalizado, cnpj_observacao = validar_cnpj(dados.get("cnpj", ""))
    telefone_status, telefone_normalizado, telefone_observacao = validar_telefone(dados.get("telefone", ""))
    data_status, data_normalizada, data_observacao = validar_data_cadastro(dados.get("data_cadastro", ""))

    return {
        "email_status": email_status,
        "email_observacao": email_observacao,
        "cnpj_status": cnpj_status,
        "cnpj_normalizado": cnpj_normalizado,
        "cnpj_observacao": cnpj_observacao,
        "telefone_status": telefone_status,
        "telefone_normalizado": telefone_normalizado,
        "telefone_observacao": telefone_observacao,
        "data_cadastro_status": data_status,
        "data_cadastro_normalizada": data_normalizada,
        "data_cadastro_observacao": data_observacao,
        "bairro_original": str(dados.get("bairro_informado", "") or ""),
        "bairro_normalizado": bairro["normalizado"],
        "bairro_canonico": bairro["canonico"],
        "subdivisao": bairro["subdivisao"],
        "cep_original": str(dados.get("cep", "") or ""),
        "cep_normalizado": cep,
        "status_cep": status_cep,
        "status_conferencia": status_conferencia,
        "observacoes": observacoes,
        "api_provedor": api["provedor"],
        "api_status": api["status"],
        "api_bairro": api["bairro"],
        "api_cidade": api["cidade"],
        "api_uf": api["uf"],
        "api_logradouro": api["logradouro"],
        "api_resposta": api["resposta"],
    }


def salvar_linha(importacao, numero_linha, dados):
    analise = analisar_registro(dados)
    return RegistroImportado.objects.create(
        importacao=importacao,
        numero_linha=numero_linha,
        dados_originais=dados,
        **analise,
    )
