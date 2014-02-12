#This file is part of sale_kit module for Tryton.
#The COPYRIGHT file at the top level of this repository contains
#the full copyright notices and license terms.
from decimal import Decimal
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Equal, Eval
from trytond.transaction import Transaction

__all__ = ['Sale', 'SaleLine']
__metaclass__ = PoolMeta


class Sale:
    __name__ = 'sale.sale'

    def create_shipment(self, shipment_type):
        pool = Pool()
        StockMove = pool.get('stock.move')
        context = Transaction().context.copy()
        context['explode_kit'] = False
        with Transaction().set_context(context):
            shipments = super(Sale, self).create_shipment(shipment_type)
        if shipments:
            for shipment in shipments:
                map_parent = {}
                map_move_sales = {}
                for move in shipment.outgoing_moves:
                    if not move.sale:
                        continue
                    for sale_line in move.sale.lines:
                        if move.product == sale_line.product:
                            break
                    else:
                        continue
                    map_parent[move.id] = (sale_line.kit_parent_line and
                            sale_line.kit_parent_line.id or False)
                    map_move_sales[sale_line.id] = move.id
                    if map_parent.get(move.id):
                        sale_parent_line = map_parent[move.id]
                        parent_move = map_move_sales.get(sale_parent_line)
                        data = {
                            'kit_parent_line': parent_move,
                            }
                        StockMove.write([move], data)
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
            if (line.product and line.product.kit_lines
                    and line.product.explode_kit_in_sales):
                for kit_line in line.product.kit_lines:
                    product = kit_line.product
                    sale_line = SaleLine()
                    sale_line.product = product
                    sale_line.quantity = ProductUom.compute_qty(
                        kit_line.unit, kit_line.quantity, line.unit
                        ) * line.quantity
                    sale_line.unit = line.unit
                    sale_line.sale = line.sale
                    sale_line.type = 'line'
                    sale_line.sequence = line.sequence + kit_line.sequence
                    sale_line.kit_parent_line = line
                    sale_line.description = ''
                    defaults = sale_line.on_change_product()
                    sale_line.kit_depth = depth
                    sale_line.description = ('%s%s' %
                        ('> ' * depth, defaults['description'])
                        if defaults.get('description') else ' ')
                    if kit_line.get_sale_price():
                        sale_line.unit_price = Product.get_sale_price(
                            [product], 0)[product.id]
                    else:
                        sale_line.unit_price = Decimal('0.0')
                    sale_line.save()
                    result.append(sale_line)
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
    def write(cls, lines, values):
        reset_kit = False
        if 'product' in values or 'quantity' in values or 'unit' in values:
            reset_kit = True
        lines = lines[:]
        if reset_kit:
            to_delete = []
            for line in lines:
                to_delete += line.get_kit_lines()
            cls.delete(to_delete)
            lines = list(set(lines) - set(to_delete))
        res = super(SaleLine, cls).write(lines, values)
        if reset_kit:
            cls.explode_kit(lines)
        return res
