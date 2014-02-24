#This file is part of sale_kit module for Tryton.
#The COPYRIGHT file at the top level of this repository contains
#the full copyright notices and license terms.
from trytond.pool import Pool
from .product import *
from .invoice import *
from .sale import *


def register():
    Pool.register(
        Product,
        ProductKitLine,
        InvoiceLine,
#        Sale,
        SaleLine,
        module='sale_kit', type_='model')
