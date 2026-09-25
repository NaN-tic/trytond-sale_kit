from proteus import Model, Wizard
from trytond.modules.sale_kit.tests import test_scenario_kit_shipments
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestKitUnits(test_scenario_kit_shipments.TestKitShipments):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        activate_modules('sale_kit')
        self.setup_company()
        Product = Model.get('product.product')
        Uom = Model.get('product.uom')
        meter, = Uom.find([('name', '=', 'Meter')])
        centimeter, = Uom.find([('name', '=', 'Centimeter')])
        pair = Uom(name='Pair', symbol='pair', category=self.unit.category,
            factor=2, rate=0.5, rounding=0.5, digits=1)
        pair.save()
        component = self.make_product('Cable')
        component.template.default_uom = meter
        component.template.save()
        component.reload()
        inner = self.make_product('Inner Kit')
        inner.kit = True
        inner.explode_kit_in_sales = False
        inner.stock_depends_on_kit_components = True
        line = inner.kit_lines.new()
        line.product = component
        line.unit = centimeter
        line.quantity = 50
        inner.save()

        outer = self.make_product('Outer Kit')
        # Exercise server-side normalization, without the checkbox on-change.
        Product._proxy.write([outer.id], {
                'kit': True, 'stock_depends_on_kit_components': True,
                'explode_kit_in_sales': False, 'kit_fixed_list_price': True,
                }, Product._config.context)
        outer.reload()
        self.assertTrue(outer.consumable)
        self.assertEqual(outer.type, 'goods')
        line = outer.kit_lines.new()
        line.product = inner
        line.quantity = 2
        line = outer.kit_lines.new()
        line.product = component
        line.unit = centimeter
        line.quantity = 25
        outer.save()
        self.supply(component, 10)

        sale = self.make_sale(outer, 10)
        shipment, = sale.shipments
        shipment.click('draft')
        move, = shipment.outgoing_moves
        move.unit = pair
        move.quantity = 5
        shipment.save()
        shipment.click('wait')
        child, = shipment.kit_component_shipments
        component_move, = child.outgoing_moves
        self.assertEqual(component_move.product, component)
        self.assertEqual(component_move.unit, meter)
        self.assertEqual(component_move.quantity, 12.5)

        assign = Wizard('stock.shipment.assign', [shipment])
        self.assertEqual(assign.form_state, 'partial')
        assign.execute('ignore')
        shipment.reload()
        move, = shipment.outgoing_moves
        self.assertEqual(move.quantity, 4)
        child = self.finish(shipment)
        component_move, = child.outgoing_moves
        self.assertEqual(component_move.quantity, 10)
        self.assertFalse(component_move.invoice_lines)
