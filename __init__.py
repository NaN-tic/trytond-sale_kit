# This file is part of sale_kit module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import product
from . import invoice
from . import sale


def register():
    Pool.register(
        product.Product,
        product.ProductKitLine,
        invoice.InvoiceLine,
        sale.SaleLine,
        module='sale_kit', type_='model')
    Pool.register(
        sale.ReturnSale,
        module='sale_kit', type_='wizard')
