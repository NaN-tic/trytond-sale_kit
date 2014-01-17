#This file is part of sale_kit module for Tryton.
#The COPYRIGHT file at the top level of this repository contains
#the full copyright notices and license terms.
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool

__all__ = ['Product', 'ProductKitLine']
__metaclass__ = PoolMeta
STATES = {
    'invisible': Bool(~Eval('kit')),
}
DEPENDS = ['kit']


class Product:
    __name__ = "product.product"
    explode_kit_in_sales = fields.Boolean('Explode in Sales', states=STATES,
            depends=DEPENDS)

    @staticmethod
    def default_explode_kit_in_sales():
        return True

    @staticmethod
    def default_kit_fixed_list_price():
        return True

    @classmethod
    def __setup__(cls):
        super(Product, cls).__setup__()
        cls._constraints += [
            ('check_required_salable_products_in_kits',
                'salable_product_required_in_kit'),
            ]
        cls._error_messages.update({
                'salable_product_required_in_kit':
                    'The products in a Kit with the flag "Explode in Sales" '
                    'checked must to be "Salables".',
                })

    def check_required_salable_products_in_kits(self):
        kit_line_obj = Pool().get('product.kit.line')
        n_not_salable_lines = kit_line_obj.search_count([
                ('parent', 'in', [self.id]),
                ('parent.explode_kit_in_sales', '=', True),
                ('product.salable', '=', False),
                ])
        if n_not_salable_lines:
            return False
        n_kits_explode_in_sales = kit_line_obj.search_count([
                ('product', 'in', [self.id]),
                ('product.salable', '=', False),
                ('parent.explode_kit_in_sales', '=', True),
                ])
        if n_kits_explode_in_sales:
            return False
        return True


class ProductKitLine:
    __name__ = 'product.kit.line'

    @classmethod
    def __setup__(cls):
        super(ProductKitLine, cls).__setup__()
        cls._constraints += [
            ('check_required_salable_lines', 'salable_lines_required'),
            ]
        cls._error_messages.update({
                'salable_lines_required':
                    'The lines of a Kit with the flag "Explode in Sales" '
                    'checked must to be "Salables".',
                })

    def get_sale_price(self):
        parent = self.parent
        if parent.kit_fixed_list_price:
            return False
        parent_kit_lines = self.search([
                ("product", "=", parent.id),
                ])
        for line in parent_kit_lines:
            if line in [x for x in line.product.kit_lines]:
                return line.get_sale_price()
        return True

    @classmethod
    def check_required_salable_lines(cls, kit_lines):
        for kit_line in cls.browse(kit_lines):
            if (kit_line.parent.explode_kit_in_sales and
                    not kit_line.product.salable):
                return False
        return True
