#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
from trytond.model import ModelView, ModelSQL, fields
from trytond.pyson import Eval, Bool, Not
from trytond.transaction import Transaction
from trytond.pool import Pool
from decimal import Decimal
import copy

class InvoiceLine(ModelSQL, ModelView):
    'Invoice Line'
    _name = 'account.invoice.line'

    def __init__(self):
        super(InvoiceLine, self).__init__()
        self.unit_price = copy.copy(self.unit_price)
        self.unit_price.states['required'] = False
        self._reset_columns()
        
InvoiceLine()

class Sale(ModelWorkflow, ModelSQL, ModelView):
    'Sale'
    _name = 'sale.sale'


    def create_shipment(self, sale_id):
        with Transaction().
        super(Sale,self).create_shipment(sale_id)
    
class SaleLine(ModelSQL, ModelView):
    _name = "sale.line"

    kit_depth = fields.Integer('Depth', required=True, 
            help='Depth of the line if it is part of a kit.')
    kit_parent_line = fields.Many2One('sale.line', 'Parent Kit Line', 
            help='The kit that contains this product.')
    kit_child_lines = fields.One2Many('sale.line', 'kit_parent_line', 
            'Lines in the kit', help='Subcomponents of the kit.')

    def default_kit_depth(self):
        return 0


    def get_kit_line(self, line, kit_line, depth):
        """
        Given a line browse object and a kit dictionary returns the
        dictionary of fields to be stored in a create statement.
        """
        res = {}
        print "KIT: ", kit_line
        # TODO: Take unit into account
        quantity = kit_line.quantity * line.quantity
        res['product'] = kit_line.product.id
        res['quantity'] = quantity
        res['unit'] = line.unit.id
        res['sale'] = line.sale.id
        res['type'] = 'line'
        res['sequence'] = line.sequence + kit_line.sequence
        res['description'] = ''
        res['kit_depth'] = depth
        res['kit_parent_line'] = line.id

        vals = {
            'product': kit_line.product.id,
            'quantity': quantity,
            'unit': line.unit.id,
            'sale_unit':line.unit.id,
            '_parent_sale.party': line.sale.party.id,
            '_parent_sale.currency': line.sale.currency.id,

        }
        res.update(self.on_change_product(vals))

        if res.get('description'):
            res['description'] = '%s%s' % ('> ' * depth, 
                    res['description'])
            
        kit_obj = Pool().get("product.kit.line")
        product_obj = Pool().get("product.product")
        
        if kit_obj.get_sale_price(kit_line.id):
            res['unit_price'] = product_obj.get_sale_price(
                [kit_line.product.id], 0)[kit_line.product.id]
        else:
            res['unit_price'] = Decimal('0.0')

        return res

    def __init__(self):
        super(SaleLine, self).__init__()
        self.unit_price = copy.copy(self.unit_price)
        required = ~(Eval('kit_parent_line', False))
        self.unit_price.states['required'] = required
        self._reset_columns()

        
        
    def explode_kit(self, id, depth=1):
        """
        Walks through the Kit tree in depth-first order and returns
        a sorted list with all the components of the product.
        """
        line = self.browse(id)

        """
        If no product on Sale Line avoid to try explode kits
        """
        if not line.product:
            return []
            
        result = []
        for kit_line in line.product.kit_lines:
            values = self.get_kit_line(line, kit_line, depth)
            new_id = self.create(values)
            self.explode_kit(new_id, depth+1)
        return result

    def create(self, values):
        id = super(SaleLine, self).create(values)
        self.explode_kit(id)
        return id

    def kit_tree_ids(self, line):
        res = []
        for kit_line in line.kit_child_lines:
            res.append(kit_line.id)
            res += self.kit_tree_ids(kit_line)
        return res

    def write(self, ids, values):
        reset_kit = False
        if 'product' in values or 'quantity' in values or 'unit' in values:
            reset_kit = True

        if isinstance(ids, (int, long)):
            ids = [ids]
        ids = ids[:]

        if reset_kit:
            to_delete = []
            for line in self.browse(ids):
                to_delete += self.kit_tree_ids(line)
            self.delete(to_delete)
            ids = list(set(ids) - set(to_delete))
        res = super(SaleLine, self).write(ids, values)
        if reset_kit:
            for id in ids:
                self.explode_kit(id)
        return res

SaleLine()
