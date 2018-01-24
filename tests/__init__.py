# This file is part of sale_kit module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
try:
    from trytond.modules.sale_kit.tests.test_sale_kit import suite
except ImportError:
    from .test_sale_kit import suite

__all__ = ['suite']
