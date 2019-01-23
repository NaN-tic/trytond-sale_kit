# This file is part of sale_kit module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool
from trytond.transaction import Transaction
from trytond.i18n import gettext
from trytond.exceptions import UserError

__all__ = ['Product', 'ProductKitLine']
STATES = {
    'invisible': Bool(~Eval('kit')),
}
DEPENDS = ['kit']


class Product(metaclass=PoolMeta):
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
    def validate(cls, products):
        super(Product, cls).validate(products)
        for product in products:
            product.check_required_salable_products_in_kits()

    def check_required_salable_products_in_kits(self):
        KitLine = Pool().get('product.kit.line')

        if not self.kit:
            return

        n_not_salable_lines = KitLine.search_count([
                ('parent', 'in', [self.id]),
                ('product.salable', '=', False),
                ('parent.explode_kit_in_sales', '=', True),
                ])
        if n_not_salable_lines:
            raise UserError(gettext('sale_kit.salable_product_required_in_kit',
                product=self.rec_name))

    @classmethod
    def get_sale_price(cls, products, quantity=0):
        '''
        Return the sale price for products and quantity.
        It uses if exists from the context:
            uom: the unit of measure
            currency: the currency id for the returned price
        '''
        pool = Pool()
        Uom = pool.get('product.uom')
        User = pool.get('res.user')
        Currency = pool.get('currency.currency')
        Date = pool.get('ir.date')

        today = Date.today()
        prices = {}

        uom = None
        if Transaction().context.get('uom'):
            uom = Uom(Transaction().context.get('uom'))

        currency = None
        if Transaction().context.get('currency'):
            currency = Currency(Transaction().context.get('currency'))

        user = User(Transaction().user)

        todo_products = []
        for product in products:
            if not product.kit or product.kit_fixed_list_price:
                todo_products.append(product)
                continue
            if product.explode_kit_in_sales:
                prices[product.id] = Decimal('0.0')
                continue

            product_price = Decimal('0.0')
            for kit_line in product.kit_lines:
                with Transaction().set_context(uom=kit_line.unit):
                    product_price += (cls.get_sale_price([kit_line.product],
                            quantity=kit_line.quantity)[kit_line.product.id] *
                        Decimal(str(kit_line.quantity)))
            prices[product.id] = product_price

            if uom:
                prices[product.id] = Uom.compute_price(
                    product.default_uom, prices[product.id], uom)
            if currency and user.company:
                if user.company.currency != currency:
                    date = Transaction().context.get('sale_date') or today
                    with Transaction().set_context(date=date):
                        prices[product.id] = Currency.compute(
                            user.company.currency, prices[product.id],
                            currency, round=False)

        if todo_products:
            prices.update(super(Product, cls).get_sale_price(todo_products,
                    quantity))

        return prices


class ProductKitLine(metaclass=PoolMeta):
    __name__ = 'product.kit.line'


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
    def validate(cls, lines):
        super(ProductKitLine, cls).validate(lines)
        for line in lines:
            line.check_required_salable_lines()

    def check_required_salable_lines(self):
        if (self.parent.explode_kit_in_sales and
                not self.product.salable):
            raise UserError(gettext('sale_kit.salable_lines_required'))
