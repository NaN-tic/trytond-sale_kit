from proteus import Model, Wizard
from trytond.model.exceptions import AccessError
from trytond.model.modelview import AccessButtonError
from trytond.modules.sale_kit.tests import test_scenario_kit_shipments
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestKitProtection(test_scenario_kit_shipments.TestKitShipments):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def assert_protected(self, shipment):
        Shipment = Model.get('stock.shipment.out')
        Move = Model.get('stock.move')
        context = Shipment._config.context
        child, = shipment.kit_component_shipments
        child_id = child.id
        for values in [
                {'reference': 'Manual change'},
                {'kit_parent_shipment': None},
                {'state': 'draft'},
                ]:
            with self.assertRaises(AccessError):
                Shipment._proxy.write([child_id], values, context)
        for action in ['draft', 'wait', 'assign_try', 'assign_force',
                'pick', 'pack', 'ship', 'do', 'cancel']:
            with self.assertRaises((AccessError, AccessButtonError)):
                getattr(Shipment._proxy, action)([child_id], context)
        with self.assertRaises(AccessError):
            Shipment._proxy.delete([child_id], context)
        with self.assertRaises(AccessError):
            Shipment._proxy.copy([child_id],
                {'kit_parent_shipment': None}, context)
        # A client-supplied context must not authorize component changes.
        with self.assertRaises(AccessError):
            Shipment._proxy.write([child_id], {'reference': 'Manual'},
                dict(context, _kit_shipment_sync=True))

        for move in child.moves:
            for values in [
                    {'quantity': 1}, {'state': 'done'},
                    {'kit_parent_move': None}, {'shipment': None},
                    ]:
                with self.assertRaises(AccessError):
                    Move._proxy.write([move.id], values, context)
            for action in ['draft', 'do', 'cancel']:
                if (move.state, action) in {
                        ('draft', 'do'),
                        ('draft', 'cancel'), ('assigned', 'draft'),
                        ('assigned', 'do'), ('assigned', 'cancel')}:
                    with self.assertRaises((AccessError, AccessButtonError)):
                        getattr(Move._proxy, action)([move.id], context)
            with self.assertRaises(AccessError):
                Move._proxy.delete([move.id], context)
            with self.assertRaises(AccessError):
                Move._proxy.copy([move.id], {
                        'kit_parent_move': None, 'shipment': None,
                        'origin': None}, context)

        component_move = child.outgoing_moves[0]
        # Inserting a move without kit metadata must also be rejected.
        with self.assertRaises(AccessError):
            Move._proxy.create([{
                        'product': component_move.product.id,
                        'unit': component_move.unit.id,
                        'quantity': 1,
                        'from_location': component_move.from_location.id,
                        'to_location': component_move.to_location.id,
                        'company': component_move.company.id,
                        'unit_price': component_move.unit_price,
                        'currency': (component_move.currency.id
                            if component_move.currency else None),
                        'shipment': 'stock.shipment.out,%s' % child_id,
                        }], context)
        child.reload()
        self.assertEqual(child.kit_parent_shipment, shipment)

    def assert_cancel_removes_components(self, shipment):
        Shipment = Model.get('stock.shipment.out')
        Move = Model.get('stock.move')
        child, = shipment.kit_component_shipments
        move_ids = [m.id for m in child.moves]
        shipment.click('cancel')
        self.assertEqual(shipment.state, 'cancelled')
        self.assertFalse(shipment.kit_component_shipments)
        self.assertFalse(Shipment.find([('id', '=', child.id)]))
        self.assertFalse(Move.find([('id', 'in', move_ids)]))
        self.assertTrue(all(m.state == 'cancelled' for m in shipment.moves))

    def test(self):
        activate_modules('sale_kit')
        self.setup_company()
        for separate_output in [True, False]:
            with self.subTest(separate_output=separate_output):
                if not separate_output:
                    self.warehouse.output_location = (
                        self.warehouse.storage_location)
                    self.warehouse.save()
                component = self.make_product('Component')
                kit = self.make_product('Kit')
                kit.kit = True
                kit.explode_kit_in_sales = False
                kit.stock_depends_on_kit_components = True
                kit.kit_fixed_list_price = True
                line = kit.kit_lines.new()
                line.product = component
                line.quantity = 1
                kit.save()
                self.supply(component, 10)

                # Waiting auxiliaries are read-only and removed on cancel.
                sale = self.make_sale(kit, 20)
                shipment, = sale.shipments
                self.assert_protected(shipment)
                self.assert_cancel_removes_components(shipment)

                # Partially reserved component moves must also be removed.
                sale = self.make_sale(kit, 20)
                shipment, = sale.shipments
                assign = Wizard('stock.shipment.assign', [shipment])
                self.assertEqual(assign.form_state, 'partial')
                assign.execute('end')
                self.assert_protected(shipment)
                self.assert_cancel_removes_components(shipment)

                # Cancellation releases stock for the next kit shipment.
                sale = self.make_sale(kit, 10)
                shipment, = sale.shipments
                Wizard('stock.shipment.assign', [shipment])
                self.assertEqual(shipment.state, 'assigned')
                self.assert_protected(shipment)
                self.assert_cancel_removes_components(shipment)

                # Normal kit transitions still manage all component moves.
                sale = self.make_sale(kit, 10)
                shipment, = sale.shipments
                Wizard('stock.shipment.assign', [shipment])
                self.assertEqual(shipment.state, 'assigned')
                child = self.finish(shipment)
                self.assertTrue(all(m.state == 'done' for m in child.moves))
                self.assert_protected(shipment)
