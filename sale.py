# This file is part of sale_kit module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Equal, Eval
from trytond.transaction import Transaction

__all__ = ['SaleLine']


class SaleLine(metaclass=PoolMeta):
    __name__ = 'sale.line'
    kit_depth = fields.Integer('Depth', required=True,
        help='Depth of the line if it is part of a kit.')
    kit_parent_line = fields.Many2One('sale.line', 'Parent Kit Line',
        help='The kit that contains this product.')
    kit_child_lines = fields.One2Many('sale.line', 'kit_parent_line',
        'Lines in the kit', help='Subcomponents of the kit.')

    @classmethod
    def __setup__(cls):
        super(SaleLine, cls).__setup__()
        required = (~(Eval('kit_parent_line', False))
            and (Equal(Eval('type'), 'line')))
        cls.unit_price.states['required'] = required

    @classmethod
    def default_kit_depth(cls):
        return 0

    def _fill_line_from_kit_line(self, kit_line, line):
        ProductUom = Pool().get('product.uom')

        self.product = kit_line.product
        if kit_line.unit.category.id != line.unit.category.id:
            quantity = kit_line.quantity * line.quantity
        else:
            quantity = ProductUom.compute_qty(
                    kit_line.unit, kit_line.quantity, line.unit
                    ) * line.quantity
        self.quantity = quantity
        self.unit = kit_line.unit
        self.type = 'line'
        self.kit_parent_line = line

    @classmethod
    def explode_kit(cls, lines):
        '''
        Walks through the Kit tree in depth-first order and returns
        a sorted list with all the components of the product.
        If no product on Sale Line avoid to try explode kits
        '''
        def max_sequence(sale_lines):
            return max([sl.sequence for sl in sale_lines] +
                [max_sequence(sl.kit_child_lines) for sl in sale_lines
                    if sl.kit_child_lines])

        Product = Pool().get('product.product')

        sale_discount = hasattr(cls, 'gross_unit_price')

        sequence = lines[0].sequence if lines and lines[0].sequence else 1
        to_write, to_create = [], []
        for line in lines:
            if line.sequence != sequence and to_create:
                line.sequence = sequence
            sequence += 1
            depth = line.kit_depth + 1
            if (line.product and line.product.kit and line.product.kit_lines
                    and line.product.explode_kit_in_sales):
                kit_lines = line.product.kit_lines
                kit_lines = list(zip(kit_lines, [depth] * len(list(kit_lines))))
                while kit_lines:
                    kit_line = kit_lines.pop(0)
                    depth = kit_line[1]
                    kit_line = kit_line[0]
                    product = kit_line.product

                    sale_line = cls()
                    for key, value in list(sale_line.default_get(
                            list(sale_line._fields.keys()),
                            with_rec_name=False).items()):
                        if value is not None:
                            setattr(sale_line, key, value)
                    # add party/sid when create new line with
                    # sale_line_standalone or galatea_esale
                    if hasattr(line, 'party'):
                        sale_line.party = line.party
                    if hasattr(line, 'sid'):
                        sale_line.sid = line.sid
                    sale_line.sale = line.sale
                    sale_line._fill_line_from_kit_line(kit_line, line)
                    sale_line.sequence = sequence
                    sale_line.on_change_product()
                    sale_line.kit_depth = depth

                    if kit_line.get_sale_price():
                        with Transaction().set_context(
                                sale_line._get_context_sale_price()):
                            prices = Product.get_sale_price(
                                [product], line.quantity)
                            unit_price = prices[product.id]
                            digits = cls.unit_price.digits[1]
                            unit_price = unit_price.quantize(
                                Decimal(1) / 10 ** digits)
                    else:
                        unit_price = Decimal('0.0')

                    # Compatibility with sale_discount module
                    if sale_discount:
                        sale_line.gross_unit_price = unit_price
                        if line.discount:
                            sale_line.discount = line.discount
                        sale_line.on_change_discount()
                    else:
                        sale_line.unit_price = unit_price

                    to_create.append(sale_line._save_values)
                    if product.kit_lines:
                        product_kit_lines = product.kit_lines
                        product_kit_lines = zip(product_kit_lines,
                            [depth + 1] * len(list(product_kit_lines)))
                        kit_lines = product_kit_lines + kit_lines
                    sequence += 1
                if not line.product.kit_fixed_list_price and line.unit_price:
                    line.unit_price = Decimal('0.0')
            elif (line.product and line.product.kit_lines and
                    not line.product.kit_fixed_list_price):
                with Transaction().set_context(
                        line._get_context_sale_price()):
                    prices = Product.get_sale_price(
                        [line.product], line.quantity)
                    unit_price = prices[line.product.id]

                # Compatibility with sale_discount module
                if sale_discount:
                    line.gross_unit_price = unit_price
                    line.on_change_discount()
                else:
                    # Avoid modifing when not required
                    if line.unit_price != unit_price:
                        line.unit_price = unit_price
            if line._save_values:
                to_write.extend(([line], line._save_values))
        if to_write:
            cls.write(*to_write)
        # Call super create to avoid recursion error
        return super(SaleLine, cls).create(to_create)

    @classmethod
    def create(cls, values):
        lines = super(SaleLine, cls).create(values)
        if (Transaction().context.get('explode_kit', True)
                and not Transaction().context.get('standalone', False)):
            lines.extend(cls.explode_kit(lines))
        return lines

    def get_kit_lines(self, kit_line=None):
        res = []
        if kit_line:
            childs = kit_line.kit_child_lines
        else:
            childs = self.kit_child_lines
        for kit_line in childs:
            res.append(kit_line)
            res += self.get_kit_lines(kit_line)
        return res

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        to_write, to_reset, to_delete = [], [], []
        if (Transaction().context.get('explode_kit', True)
                and not Transaction().context.get('standalone', False)):
            for lines, values in zip(actions, actions):
                reset_kit = False
                # TODO Explode kit when add new line from standalone
                if ('product' in values or 'quantity' in values
                        or 'unit' in values):
                    reset_kit = True
                lines = lines[:]
                if reset_kit:
                    for line in lines:
                        to_delete += line.get_kit_lines()
                    lines = list(set(lines) - set(to_delete))
                    to_reset.extend(lines)
                to_write.extend((lines, values))
        else:
            to_write = args
        super(SaleLine, cls).write(*to_write)
        if to_delete:
            cls.delete(to_delete)
        if to_reset:
            cls.explode_kit(to_reset)

    @classmethod
    def copy(cls, lines, default=None):
        if default is None:
            default = {}
        default['kit_child_lines'] = []
        lines = [x for x in lines if not x.kit_parent_line]
        new_lines = super(SaleLine, cls).copy(lines, default=default)
        return new_lines

    def get_invoice_line(self):
        lines = super(SaleLine, self).get_invoice_line()
        for line in lines:
            line.sequence = self.sequence
        return lines

