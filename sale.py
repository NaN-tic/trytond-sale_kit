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
        def max_sequence(sale_lines):
            return max([sl.sequence for sl in sale_lines] +
                [max_sequence(sl.kit_child_lines) for sl in sale_lines
                    if sl.kit_child_lines])

        pool = Pool()
        Product = pool.get('product.product')
        ProductUom = pool.get('product.uom')
        sequence = lines[0].sequence if lines and lines[0].sequence else 1
        to_write, to_create = [], []
        for line in lines:
            if line.sequence != sequence and to_create:
                line.sequence = sequence
            sequence += 1
            depth = line.kit_depth + 1
            if (line.product and line.product.kit and line.product.kit_lines
                    and line.product.explode_kit_in_sales):
                kit_lines = list(line.product.kit_lines)
                kit_lines = zip(kit_lines, [depth] * len(kit_lines))
                while kit_lines:
                    kit_line = kit_lines.pop(0)
                    depth = kit_line[1]
                    kit_line = kit_line[0]
                    product = kit_line.product
                    sale_line = cls()
                    sale_line.sale = line.sale
                    sale_line.product = product
                    sale_line.quantity = ProductUom.compute_qty(
                        kit_line.unit, kit_line.quantity, line.unit
                        ) * line.quantity
                    sale_line.unit = line.unit
                    sale_line.type = 'line'
                    sale_line.sequence = sequence
                    sale_line.kit_parent_line = line
                    sale_line.description = ''
                    defaults = sale_line.on_change_product()
                    for fname, fvalue in defaults.items():
                        setattr(sale_line, fname, fvalue)
                    sale_line.kit_depth = depth
                    sale_line.description = ('%s%s' %
                        ('> ' * depth, defaults['description'])
                        if defaults.get('description') else ' ')

                    if kit_line.get_sale_price():
                        with Transaction().set_context(
                                sale_line._get_context_sale_price()):
                            unit_price = Product.get_sale_price(
                                [product], 0)[product.id]
                    else:
                        unit_price = Decimal('0.0')

                    # Compatibility with sale_discount module
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
                    to_create.append(sale_line._save_values)
                    if product.kit_lines:
                        product_kit_lines = list(product.kit_lines)
                        product_kit_lines = zip(product_kit_lines,
                            [depth + 1] * len(product_kit_lines))
                        kit_lines = product_kit_lines + kit_lines
                    sequence += 1
                if not line.product.kit_fixed_list_price and line.unit_price:
                    line.unit_price = Decimal('0.0')
            elif (line.product and line.product.kit_lines and
                    not line.product.kit_fixed_list_price):
                with Transaction().set_context(
                        line._get_context_sale_price()):
                    unit_price = Product.get_sale_price([line.product],
                        0)[line.product.id]
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
        if Transaction().context.get('explode_kit', True):
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
            cls.explode_kit(to_reset)

    @classmethod
    def copy(cls, lines, default=None):
        if default is None:
            default = {}
        default.setdefault('kit_child_lines', [])
        new_lines, no_kit_lines = [], []
        copied_parents = set()
        with Transaction().set_context(explode_kit=False):
            for line in lines:
                if line.kit_child_lines:
                    if not line.kit_parent_line in copied_parents:
                        new_line, = super(SaleLine, cls).copy([line], default)
                        new_lines.append(new_line)
                        copied_parents.add(line.id)
                        new_default = default.copy()
                        new_default['kit_parent_line'] = new_line.id
                        super(SaleLine, cls).copy(line.kit_child_lines,
                            default=new_default)
                elif (line.kit_parent_line and
                        line.kit_parent_line.id in copied_parents):
                    # Already copied by kit_child_lines
                    continue
                else:
                    no_kit_lines.append(line)
            new_lines += super(SaleLine, cls).copy(no_kit_lines,
                default=default)
        return new_lines

    def get_invoice_line(self, invoice_type):
        lines = super(SaleLine, self).get_invoice_line(invoice_type)
        for line in lines:
            line.sequence = self.sequence
        return lines
