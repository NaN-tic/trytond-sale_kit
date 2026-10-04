from decimal import Decimal

from proteus import Model, Wizard
from trytond.modules.sale_kit.tests import test_scenario_kit_shipments
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestExpandedKitUpgrade(test_scenario_kit_shipments.TestKitShipments):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        activate_modules('sale_kit')
        self.setup_company()
        Sale = Model.get('sale.sale')
        sale = Sale(party=self.customer, payment_term=self.payment_term,
            invoice_method='shipment', warehouse=self.warehouse)
        kits = []
        components = []
        for quantity in [10, 20]:
            component = self.make_product('Component')
            components.append(component)
            self.supply(component, quantity)
            kit = self.make_product('Service Kit')
            kit.template.type = 'service'
            kit.template.list_price = Decimal(37)
            kit.template.save()
            kit.reload()
            kit.kit = True
            kit.kit_fixed_list_price = True
            kit.explode_kit_in_sales = True
            kit.stock_depends_on_kit_components = True
            self.assertEqual(kit.template.type, 'service')
            line = kit.kit_lines.new()
            line.product = component
            line.quantity = 1
            kit.save()
            kit.reload()
            self.assertEqual(kit.type, 'service')
            kits.append(kit)
            line = sale.lines.new()
            line.product = kit
            line.quantity = quantity
        sale.click('quote')
        sale.click('confirm')
        self.assertEqual(len(sale.lines), 4)
        self.assertFalse(sale.kit_component_shipments)
        self.assertEqual(sum(line.quantity for invoice in sale.invoices
                for line in invoice.lines if line.product in kits), 30)
        shipment, = sale.shipments
        self.assertEqual({m.product for m in shipment.outgoing_moves},
            set(components))
        Wizard('stock.shipment.assign', [shipment])
        shipment.click('pick')
        shipment.click('pack')
        shipment.click('ship')
        shipment.click('do')
        sale.reload()
        invoice_ids = {i.id for i in sale.invoices}
        shipment_ids = {s.id for s in sale.shipments}
        move_ids = {m.id for s in sale.shipments for m in s.moves}

        # Upgrade with an existing invoice and delivered components. The old
        # global migration changed service kits here and caused late moves
        # and negative invoice quantities on the next sale processing.
        Module = Model.get('ir.module')
        modules = Module.find([('name', 'in', ['stock_kit', 'sale_kit'])])
        Module.click(modules, 'upgrade')
        Wizard('ir.module.activate_upgrade').execute('upgrade')
        Product = Model.get('product.product')
        for kit in kits:
            kit = Product(kit.id)
            self.assertEqual(kit.type, 'service')
            self.assertFalse(kit.consumable)
        sale = Model.get('sale.sale')(sale.id)
        for invoice in sale.invoices:
            invoice.click('post')
        sale.click('process')
        sale.reload()
        self.assertEqual({i.id for i in sale.invoices}, invoice_ids)
        self.assertEqual({s.id for s in sale.shipments}, shipment_ids)
        self.assertEqual({m.id for s in sale.shipments for m in s.moves},
            move_ids)
        self.assertFalse(sale.kit_component_shipments)
        self.assertTrue(all(line.quantity >= 0
                for invoice in sale.invoices for line in invoice.lines))
        self.assertEqual(sum(invoice.untaxed_amount
                for invoice in sale.invoices),
            Decimal(1110))
