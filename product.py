#This file is part sale_kit module for Tryton.
#The COPYRIGHT file at the top level of this repository contains 
#the full copyright notices and license terms.
from trytond.model import ModelView, ModelSQL, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool

__all__ = ['Product', 'ProductKitLine']
__metaclass__ = PoolMeta
STATES = {
    'readonly': Bool(~Eval('kit')),
}
DEPENDS = ['stock_kit']


class Product:
    __name__ = "product.product"
    explode_kit_in_sales = fields.Boolean('Explode in Sales', states=STATES,
            depends=DEPENDS)
    kit_fixed_list_price = fields.Boolean('Fixed List Price', states=STATES,
            depends=DEPENDS, help='Mark this '
            'field if the list price of the kit should be fixed. Do not mark '
            'it if the price should be calculated from the sum of the prices '
            'of the products in the pack.')

    @staticmethod
    def default_explode_kit_in_sales():
        return True

    @staticmethod
    def default_kit_fixed_list_price():
        return True

    @classmethod
    def __setup__(cls):
       
        super(Product, cls).__setup__()
        self._constraints += [
            ('check_required_salable_products_in_kits',
                    'salable_product_required_in_kit'),
        ]
        self._error_messages.update({
            'salable_product_required_in_kit': 'The products in a Kit with ' \
                    'the flag "Explode in Sales" checked must to be ' \
                    '"Salables".'
        })

    def check_required_salable_products_in_kits(self, ids):
        kit_line_obj = Pool().get('product.kit.line')
        n_not_salable_lines = kit_line_obj.search_count([
                    ('parent', 'in', ids),
                    ('parent.explode_kit_in_sales', '=', True),
                    ('product.salable', '=', False),
                ])
        if n_not_salable_lines:
            return False
        n_kits_explode_in_sales = kit_line_obj.search_count([
                    ('product', 'in', ids),
                    ('product.salable', '=', False),
                    ('parent.explode_kit_in_sales', '=', True),
                ])
        if n_kits_explode_in_sales:
            return False
        return True


class ProductKitLine(ModelSQL, ModelView):
    '''Product Kit'''
    __name__ = 'product.kit.line'

    def get_sale_price(self, line):
        kit_line = self.browse(line)
        parent = kit_line.parent
        if parent.kit_fixed_list_price:
            return False
        parent_kit_lines = self.search([
                    ("product", "=", parent.id),
                ])
        for line in self.browse(parent_kit_lines):
            if line in [x.id for x in line.product.kit_lines]:
                return self.get_sale_price(self, line.id)
        return True

    def __init__(self):
        super(ProductKitLine, self).__init__()
        self._constraints += [
            ('check_required_salable_lines', 'salable_lines_required'),
        ]
        self._error_messages.update({
            'salable_lines_required': 'The lines of a Kit with the flag ' \
                    '"Explode in Sales" checked must to be "Salables".'
        })

    def check_required_salable_lines(self, ids):
        for kit_line in self.browse(ids):
            if (kit_line.parent.explode_kit_in_sales and
                    not kit_line.product.salable):
                return False
        return True
