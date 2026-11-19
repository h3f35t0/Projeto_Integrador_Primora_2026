from django.conf import settings
from django.db import models


class ImportacaoArquivo(models.Model):
    nome_arquivo = models.CharField(max_length=255)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    criado_em = models.DateTimeField(auto_now_add=True)
    total_registros = models.PositiveIntegerField(default=0)
    total_cep_ausente = models.PositiveIntegerField(default=0)
    total_cep_invalido = models.PositiveIntegerField(default=0)
    total_conflitos = models.PositiveIntegerField(default=0)
    observacoes = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.nome_arquivo} ({self.criado_em:%d/%m/%Y %H:%M})"


class ReferenciaCEP(models.Model):
    """Tabela de referência postal mantida pela equipe; não vem pré-preenchida."""
    cep = models.CharField(max_length=8, unique=True, help_text="Somente os oito dígitos")
    bairro_canonico = models.CharField(max_length=100)
    subdivisao = models.CharField(max_length=100, blank=True)
    fonte = models.CharField(max_length=255, blank=True, help_text="Ex.: consulta oficial dos Correios")
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["cep"]
        verbose_name = "Referência de CEP"
        verbose_name_plural = "Referências de CEP"

    def __str__(self):
        return f"{self.cep} - {self.bairro_canonico}"


class RegistroImportado(models.Model):
    STATUS_CEP = [
        ("AUSENTE", "Ausente"),
        ("INVALIDO", "Inválido"),
        ("FORMATO_VALIDO", "Formato válido; não verificado"),
    ]
    STATUS_CONFERENCIA = [
        ("NAO_VERIFICADO", "Não verificado: sem referência postal"),
        ("COMPATIVEL", "Compatível com referência cadastrada"),
        ("CONFLITO", "Conflito entre bairro e CEP"),
        ("DIVERGENCIA_API", "Bairro divergente da consulta à API"),
        ("BAIRRO_NAO_IDENTIFICADO", "Bairro não identificado"),
    ]

    importacao = models.ForeignKey(ImportacaoArquivo, related_name="registros", on_delete=models.CASCADE)
    numero_linha = models.PositiveIntegerField()
    dados_originais = models.JSONField(default=dict)
    bairro_original = models.CharField(max_length=255, blank=True)
    bairro_normalizado = models.CharField(max_length=255, blank=True)
    bairro_canonico = models.CharField(max_length=100, blank=True)
    subdivisao = models.CharField(max_length=100, blank=True)
    cep_original = models.CharField(max_length=40, blank=True)
    cep_normalizado = models.CharField(max_length=8, blank=True)
    status_cep = models.CharField(max_length=20, choices=STATUS_CEP)
    status_conferencia = models.CharField(max_length=30, choices=STATUS_CONFERENCIA)
    observacoes = models.JSONField(default=list, blank=True)
    api_provedor = models.CharField(max_length=30, blank=True)
    api_status = models.CharField(max_length=30, default="NAO_CONSULTADO")
    api_bairro = models.CharField(max_length=150, blank=True)
    api_cidade = models.CharField(max_length=150, blank=True)
    api_uf = models.CharField(max_length=2, blank=True)
    api_logradouro = models.CharField(max_length=255, blank=True)
    api_resposta = models.JSONField(default=dict, blank=True)

    email_status = models.CharField(max_length=20, default="NAO_INFORMADO")
    email_observacao = models.CharField(max_length=255, blank=True)
    cnpj_status = models.CharField(max_length=20, default="NAO_INFORMADO")
    cnpj_normalizado = models.CharField(max_length=18, blank=True)
    cnpj_observacao = models.CharField(max_length=255, blank=True)
    telefone_status = models.CharField(max_length=20, default="NAO_INFORMADO")
    telefone_normalizado = models.CharField(max_length=20, blank=True)
    telefone_observacao = models.CharField(max_length=255, blank=True)
    data_cadastro_status = models.CharField(max_length=20, default="NAO_INFORMADO")
    data_cadastro_normalizada = models.DateField(null=True, blank=True)
    data_cadastro_observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["numero_linha"]
        verbose_name = "Registro importado"
        verbose_name_plural = "Registros importados"

    def __str__(self):
        return f"Linha {self.numero_linha} - {self.bairro_original}"


class ClienteConsolidado(models.Model):
    """Registro final persistido após a conferência do lote ETL."""
    registro_origem = models.OneToOneField(
        RegistroImportado, related_name="consolidado", on_delete=models.PROTECT
    )
    usuario_gravacao = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="clientes_consolidados_gravados", verbose_name="Usuário que gravou"
    )
    dados_originais = models.JSONField(default=dict)
    dados_ajustados = models.JSONField(default=dict)
    isvalido = models.BooleanField(default=True, db_index=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Cliente consolidado"
        verbose_name_plural = "Clientes consolidados"

    def __str__(self):
        return f"Cliente da linha {self.registro_origem.numero_linha} - válido: {self.isvalido}"
