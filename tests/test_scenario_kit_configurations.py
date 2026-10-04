from decimal import Decimal
from itertools import product

from proteus import Model, Wizard
from trytond.modules.sale_kit.tests import test_scenario_kit_shipments
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestKitConfigurations(test_scenario_kit_shipments.TestKitShipments):

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
        Template = Model.get('product.template')
        config = Product._config
        for fixed, depends, explode, initial_type in product(
                [False, True], [False, True], [False, True],
                ['service', 'goods']):
            with self.subTest(fixed=fixed, depends=depends, explode=explode,
                    initial_type=initial_type):
                component = self.make_product('Component')
                kit = self.make_product('Kit')
                # Legacy expanded goods already had to be consumable when
                # their stock depended on components; services were allowed.
                consumable = initial_type == 'goods' and depends and explode
                Template._proxy.write([kit.template.id], {
                        'type': initial_type, 'consumable': consumable,
                        }, config.context)
                Product._proxy.write([kit.id], {
                        'kit': True,
                        'kit_fixed_list_price': fixed,
                        'stock_depends_on_kit_components': depends,
                        'explode_kit_in_sales': explode,
                        }, config.context)
                kit.reload()
                line = kit.kit_lines.new()
                line.product = component
                line.quantity = 2
                kit.save()
                kit.reload()
                auxiliary = depends and not explode
                expected_type = 'goods' if auxiliary else initial_type
                self.assertEqual(kit.type, expected_type)
                self.assertEqual(kit.consumable,
                    True if auxiliary else consumable)
                # Template validation must use the same narrow rule.
                kit.template.name = 'Validated Kit'
                kit.template.save()
                kit.reload()
                self.assertEqual(kit.type, expected_type)

                self.supply(component, 6)
                if expected_type == 'goods' and not kit.consumable:
                    self.supply(kit, 3)
                sale = self.make_sale(kit, 3)
                self.assertEqual(len(sale.lines), 2 if explode else 1)
                expected_products = set()
                if expected_type == 'goods':
                    expected_products.add(kit)
                if explode:
                    expected_products.add(component)
                self.assertEqual(len(sale.shipments),
                    1 if expected_products else 0)
                self.assertEqual(len(sale.kit_component_shipments),
                    1 if auxiliary else 0)
                if explode and expected_type == 'service':
                    # Like the reported case, the parent is invoiceable before
                    # shipping, but has no stock moves of its own.
                    self.assertTrue(any(line.product == kit
                            for invoice in sale.invoices
                            for line in invoice.lines))
                    self.assertFalse(sale.lines[0].moves)
                for shipment in sale.shipments:
                    self.assertEqual({m.product
                            for m in shipment.outgoing_moves},
                        expected_products)
                    Wizard('stock.shipment.assign', [shipment])
                    self.assertEqual(shipment.state, 'assigned')
                    if shipment.warehouse_storage != shipment.warehouse_output:
                        shipment.click('pick')
                    shipment.click('pack')
                    shipment.click('ship')
                    shipment.click('do')
                    self.assertEqual(shipment.state, 'done')
                    for child in shipment.kit_component_shipments:
                        self.assertEqual(child.state, 'done')
                        self.assertEqual({m.product
                                for m in child.outgoing_moves}, {component})
                        self.assertEqual(sum(m.quantity
                                for m in child.outgoing_moves), 6)
                        self.assertTrue(all(not m.invoice_lines
                                for m in child.outgoing_moves))
                sale.reload()
                invoice_ids = {i.id for i in sale.invoices}
                shipment_ids = {s.id for s in sale.shipments}
                lines = [line for invoice in sale.invoices
                    for line in invoice.lines if line.type == 'line']
                self.assertTrue(all(line.quantity >= 0 for line in lines))
                expected_amount = Decimal(30 if fixed else 60)
                self.assertEqual(sum(Decimal(str(line.quantity))
                        * line.unit_price for line in lines), expected_amount)

                # Posting and reprocessing must not create late kit shipments
                # or credit notes for products configured before invoicing.
                for invoice in sale.invoices:
                    invoice.click('post')
                sale.click('process')
                sale.reload()
                self.assertEqual({i.id for i in sale.invoices}, invoice_ids)
                self.assertEqual({s.id for s in sale.shipments}, shipment_ids)
                self.assertEqual(len(sale.kit_component_shipments),
                    1 if auxiliary else 0)
                self.assertTrue(all(line.quantity >= 0
                        for invoice in sale.invoices for line in invoice.lines
                        if line.type == 'line'))

        # Switching the sales option must normalize only the unexpanded case.
        kit = self.make_product('Switchable Kit')
        kit.template.type = 'service'
        kit.template.save()
        kit.reload()
        kit.kit = True
        kit.stock_depends_on_kit_components = True
        self.assertEqual(kit.template.type, 'service')
        kit.save()
        kit.explode_kit_in_sales = False
        self.assertEqual(kit.type, 'goods')
        self.assertTrue(kit.consumable)
        kit.save()
        kit.reload()
        self.assertEqual(kit.type, 'goods')
        self.assertTrue(kit.consumable)
        kit.explode_kit_in_sales = True
        kit.save()
        kit.template.type = 'service'
        kit.template.consumable = False
        kit.template.save()
        kit.reload()
        self.assertEqual(kit.type, 'service')
        self.assertFalse(kit.consumable)
