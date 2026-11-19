from django.test import SimpleTestCase
from .services import normalizar_bairro, normalizar_cep

class NormalizacaoTest(SimpleTestCase):
    def test_acentos_e_caixa(self):
        self.assertEqual(normalizar_bairro("AGUAS CLARAS")["canonico"], "Águas Claras")

    def test_abreviacao_vicente_pires(self):
        self.assertEqual(normalizar_bairro("Vte Pires")["canonico"], "Vicente Pires")

    def test_guara_subdivisao(self):
        resultado = normalizar_bairro("Guará II")
        self.assertEqual(resultado["canonico"], "Guará")
        self.assertEqual(resultado["subdivisao"], "II")

    def test_cep_ausente_e_invalido(self):
        self.assertEqual(normalizar_cep("")[1], "AUSENTE")
        self.assertEqual(normalizar_cep("00000-000")[1], "INVALIDO")
        self.assertEqual(normalizar_cep("71926-750")[1], "FORMATO_VALIDO")
