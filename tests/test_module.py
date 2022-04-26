
# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.modules.company.tests import CompanyTestMixin
from trytond.tests.test_tryton import ModuleTestCase


class SaleKitTestCase(CompanyTestMixin, ModuleTestCase):
    'Test SaleKit module'
    module = 'sale_kit'


del ModuleTestCase
