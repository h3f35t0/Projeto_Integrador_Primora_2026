from django.contrib import admin
from .models import ClienteConsolidado, ImportacaoArquivo, ReferenciaCEP, RegistroImportado


@admin.register(ReferenciaCEP)
class ReferenciaCEPAdmin(admin.ModelAdmin):
    list_display = ("cep", "bairro_canonico", "subdivisao", "fonte", "ativo")
    list_filter = ("ativo", "bairro_canonico")
    search_fields = ("cep", "bairro_canonico", "subdivisao")


class RegistroInline(admin.TabularInline):
    model = RegistroImportado
    extra = 0
    readonly_fields = ("numero_linha", "bairro_original", "bairro_canonico", "subdivisao", "cep_original", "status_cep", "status_conferencia", "observacoes")
    can_delete = False


@admin.register(ImportacaoArquivo)
class ImportacaoArquivoAdmin(admin.ModelAdmin):
    list_display = ("nome_arquivo", "usuario", "criado_em", "total_registros", "total_cep_ausente", "total_cep_invalido", "total_conflitos")
    readonly_fields = ("criado_em", "total_registros", "total_cep_ausente", "total_cep_invalido", "total_conflitos", "observacoes")
    inlines = [RegistroInline]


@admin.register(RegistroImportado)
class RegistroImportadoAdmin(admin.ModelAdmin):
    list_display = ("importacao", "numero_linha", "bairro_original", "bairro_canonico", "subdivisao", "cep_original", "status_cep", "status_conferencia")
    list_filter = ("status_cep", "status_conferencia", "bairro_canonico")
    search_fields = ("bairro_original", "cep_original", "bairro_canonico")
    readonly_fields = ("importacao", "numero_linha", "dados_originais", "bairro_original", "bairro_normalizado", "bairro_canonico", "subdivisao", "cep_original", "cep_normalizado", "status_cep", "status_conferencia", "observacoes")


@admin.register(ClienteConsolidado)
class ClienteConsolidadoAdmin(admin.ModelAdmin):
    list_display = ("registro_origem", "isvalido", "criado_em")
    list_filter = ("isvalido", "criado_em")
    search_fields = ("registro_origem__bairro_original", "registro_origem__cep_original")
    readonly_fields = ("registro_origem", "dados_originais", "dados_ajustados", "isvalido", "criado_em")
