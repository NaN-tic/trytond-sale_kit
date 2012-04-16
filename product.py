#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.

from trytond.model import ModelView, ModelSQL, fields
from trytond.pyson import Eval, Bool

STATES = {
    'readonly': Bool(~Eval('kit')),
}

DEPENDS = ['stock_kit']


class Product(ModelSQL, ModelView):
    _name = "product.product"

    explode_kit_in_sales = fields.Boolean('Explode in Sales', states=STATES,
            depends=DEPENDS)
    kit_fixed_list_price = fields.Boolean('Fixed List Price', states=STATES,
            depends=DEPENDS, help='Mark this '
            'field if the list price of the kit should be fixed. Do not mark '
            'it if the price should be calculated from the sum of the prices '
            'of the products in the pack.')

    def default_explode_kit_in_sales(self):
        return True

    def default_kit_fixed_list_price(self):
        return True

Product()


class ProductKitLine(ModelSQL, ModelView):
    '''Product Kit'''
    _name = 'product.kit.line'

    def get_sale_price(self, line_id):
        print "get_sale_price"
        kit_line = self.browse(line_id)
        parent = kit_line.parent

        print "fix", parent.name, parent.kit_fixed_list_price
        if parent.kit_fixed_list_price:
            return False

        parent_kit_lines = self.search([
                    ("product", "=", parent.id),
                ])

        for line in self.browse(parent_kit_lines):
            if line_id in [x.id for x in line.product.kit_lines]:
                return self.get_sale_price(self, line.id)

        return True

ProductKitLine()
