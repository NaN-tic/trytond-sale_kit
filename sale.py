#This file is part of sale_kit module for Tryton.
#The COPYRIGHT file at the top level of this repository contains
#the full copyright notices and license terms.
from decimal import Decimal
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Equal, Eval
from trytond.transaction import Transaction

__all__ = ['SaleLine']
__metaclass__ = PoolMeta


class Sale:
    __name__ = 'sale.sale'

    def create_shipment(self, shipment_type):
        pool = Pool()
        ShipmentOut = pool.get('stock.shipment.out')
        StockMove = pool.get('stock.move')

        with Transaction().set_context(explode_kit=False):
            shipments = super(Sale, self).create_shipment(shipment_type)
        if shipment_type != 'out' or not shipments:
            return

        shipments_to_rewait = set()
        for shipment in shipments:
            map_parent = {}
            map_move_sales = {}
            for move in shipment.outgoing_moves:
                if not move.sale:
                    continue
                sale_line = move.origin
                map_parent[move.id] = (sale_line.kit_parent_line and
                        sale_line.kit_parent_line.id or False)
                map_move_sales[sale_line.id] = move.id
                if map_parent.get(move.id):
                    sale_parent_line = map_parent[move.id]
                    parent_move = map_move_sales.get(sale_parent_line)
                    data = {
                        'kit_parent_line': parent_move,
                        'kit_depth': sale_line.kit_depth,
                        }
                    StockMove.write([move], data)
                    shipments_to_rewait.add(shipment)
        if shipments_to_rewait:
            with Transaction().set_user(0, set_context=True):
                ShipmentOut.wait(list(shipments_to_rewait))
        return shipments


class SaleLine:
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

    @classmethod
    def explode_kit(cls, lines):
        '''
        Walks through the Kit tree in depth-first order and returns
        a sorted list with all the components of the product.
        If no product on Sale Line avoid to try explode kits
        '''
        pool = Pool()
        Product = pool.get('product.product')
        ProductUom = pool.get('product.uom')
        SaleLine = pool.get('sale.line')
        result = []
        for line in lines:
            depth = line.kit_depth + 1
            if (line.product and line.product.kit and line.product.kit_lines
                    and line.product.explode_kit_in_sales):
                for kit_line in line.product.kit_lines:
                    product = kit_line.product
                    sale_line = SaleLine()
                    sale_line.sale = line.sale
                    sale_line.product = product
                    sale_line.quantity = ProductUom.compute_qty(
                        kit_line.unit, kit_line.quantity, line.unit
                        ) * line.quantity
                    sale_line.unit = line.unit
                    sale_line.type = 'line'
                    sale_line.sequence = line.sequence
                    sale_line.kit_parent_line = line
                    sale_line.description = ''
                    defaults = sale_line.on_change_product()
                    sale_line.kit_depth = depth
                    sale_line.description = ('%s%s' %
                        ('> ' * depth, defaults['description'])
                        if defaults.get('description') else ' ')

                    if kit_line.get_sale_price():
                        unit_price = Product.get_sale_price(
                            [product], 0)[product.id]
                    else:
                        unit_price = Decimal('0.0')

                    if hasattr(cls, 'gross_unit_price'):
                        sale_line.gross_unit_price = unit_price
                        if line.discount:
                            sale_line.discount = line.discount
                        change_discount_vals = sale_line.on_change_discount()
                        for fname, fvalue in change_discount_vals.items():
                            setattr(sale_line, fname, fvalue)
                    else:
                        sale_line.unit_price = unit_price

                    sale_line.taxes = defaults['taxes']
                    sale_line.save()
                    result.append(sale_line)
                if not line.product.kit_fixed_list_price:
                    line.unit_price = Decimal('0.0')
                    line.save()
            elif (line.product and line.product.kit_lines and
                    not line.product.kit_fixed_list_price):
                line.unit_price = Product.get_sale_price([line.product],
                    0)[line.product.id]
                line.save()
        return result

    @classmethod
    def create(cls, values):
        lines = super(SaleLine, cls).create(values)
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
        for lines, values in zip(actions, actions):
            reset_kit = False
            if 'product' in values or 'quantity' in values or 'unit' in values:
                reset_kit = True
            lines = lines[:]
            if reset_kit:
                for line in lines:
                    to_delete += line.get_kit_lines()
                lines = list(set(lines) - set(to_delete))
                to_reset.extend(lines)
            to_write.extend((lines, values))
        super(SaleLine, cls).write(*to_write)
        if to_delete:
            cls.delete(to_delete)
        if to_reset:
            cls.explode_kit(lines)

    @classmethod
    def copy(cls, lines, default=None):
        if default is None:
            default = {}
        default = default.copy()
        lines_to_copy = []
        for line in lines:
            if line.kit_parent_line is None:
                lines_to_copy.append(line)
        res = super(SaleLine, cls).copy(lines_to_copy, default=default)
        return res

    def get_invoice_line(self, invoice_type):
        lines = super(SaleLine, self).get_invoice_line(invoice_type)
        for line in lines:
            line.sequence = self.sequence
        return lines
