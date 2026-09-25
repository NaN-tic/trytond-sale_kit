import datetime
import unittest
from decimal import Decimal

from proteus import Model, Wizard
from trytond.modules.account.tests.tools import (
    create_chart, create_fiscalyear, get_accounts)
from trytond.modules.account_invoice.tests.tools import (
    create_payment_term, set_fiscalyear_invoice_sequences)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestKitShipments(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def make_product(self, name):
        Template = Model.get('product.template')
        template = Template(
            name=name, type='goods', default_uom=self.unit, salable=True,
            list_price=Decimal('10'), account_category=self.category)
        template.save()
        product, = template.products
        return product

    def supply(self, product, quantity):
        Move = Model.get('stock.move')
        move = Move(
            product=product, unit=product.default_uom, quantity=quantity,
            from_location=self.supplier,
            to_location=self.warehouse.storage_location,
            company=self.company, unit_price=Decimal('2'),
            currency=self.company.currency,
            effective_date=datetime.date.today())
        move.save()
        move.click('do')

    def make_sale(self, product, quantity):
        Sale = Model.get('sale.sale')
        sale = Sale(party=self.customer, payment_term=self.payment_term,
            invoice_method='fulfillment', warehouse=self.warehouse)
        line = sale.lines.new()
        line.product = product
        line.quantity = quantity
        sale.click('quote')
        sale.click('confirm')
        return sale

    def finish(self, shipment):
        if shipment.warehouse_storage != shipment.warehouse_output:
            shipment.click('pick')
        shipment.click('pack')
        shipment.click('ship')
        shipment.click('do')
        self.assertEqual(shipment.state, 'done')
        child, = shipment.kit_component_shipments
        self.assertEqual(child.state, 'done')
        return child

    def setup_company(self):
        create_company()
        self.company = get_company()
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(self.company))
        fiscalyear.click('create_period')
        create_chart(self.company)
        accounts = get_accounts(self.company)
        Category = Model.get('product.category')
        self.category = Category(name='Accounting', accounting=True,
            account_expense=accounts['expense'],
            account_revenue=accounts['revenue'])
        self.category.save()
        Party = Model.get('party.party')
        self.customer = Party(name='Customer')
        self.customer.save()
        self.payment_term = create_payment_term()
        self.payment_term.save()
        Uom = Model.get('product.uom')
        self.unit, = Uom.find([('name', '=', 'Unit')])
        Location = Model.get('stock.location')
        self.warehouse, = Location.find([('type', '=', 'warehouse')])
        self.supplier, = Location.find([('type', '=', 'supplier')])

    def test(self):
        activate_modules('sale_kit')
        self.setup_company()
        Product = Model.get('product.product')
        config = Product._config

        for separate_output in [True, False]:
            with self.subTest(separate_output=separate_output):
                if not separate_output:
                    self.warehouse.output_location = (
                        self.warehouse.storage_location)
                    self.warehouse.save()
                component_a = self.make_product('A')
                component_b = self.make_product('B')
                kit = self.make_product('Kit')
                kit.kit = True
                kit.explode_kit_in_sales = False
                kit.stock_depends_on_kit_components = True
                kit.kit_fixed_list_price = True
                for component in [component_a, component_b]:
                    line = kit.kit_lines.new()
                    line.product = component
                    line.quantity = 1
                kit.save()
                kit.reload()
                self.assertEqual(kit.type, 'goods')
                self.assertTrue(kit.consumable)
                self.supply(component_a, 10)
                self.supply(component_b, 20)

                # Reserve only complete kits and expose missing components.
                sale = self.make_sale(kit, 20)
                self.assertEqual(len(sale.lines), 1)
                shipment, = sale.shipments
                child, = shipment.kit_component_shipments
                self.assertEqual(sale.kit_component_shipments, [child])
                self.assertEqual(len(child.outgoing_moves), 2)
                assign = Wizard('stock.shipment.assign', [shipment])
                self.assertEqual(assign.form_state, 'partial')
                self.assertIn('20', assign.form.kit_summary)
                self.assertIn('10', assign.form.kit_summary)
                self.assertIn(component_a,
                    [m.product for m in assign.form.moves])
                child.reload()
                reserved = (child.inventory_moves if separate_output
                    else child.outgoing_moves)
                for product in [component_a, component_b]:
                    self.assertEqual(sum(m.quantity for m in reserved
                            if m.product == product and m.state == 'assigned'),
                        10, [(m.product.name, m.quantity, m.state,
                                m.kit_component_quantity) for m in reserved])

                # Another sale cannot reserve the components already assigned.
                competing = self.make_sale(kit, 1)
                competing_shipment, = competing.shipments
                competing_assign = Wizard('stock.shipment.assign',
                    [competing_shipment])
                self.assertEqual(competing_assign.form_state, 'partial')
                competing_assign.execute('cancel')
                competing_shipment.click('cancel')

                assign.execute('ignore')
                shipment.reload()
                self.assertEqual(shipment.state, 'assigned')
                self.assertEqual(sum(m.quantity
                        for m in shipment.outgoing_moves), 10)
                child = self.finish(shipment)
                self.assertEqual(sum(m.quantity
                        for m in child.outgoing_moves), 20)
                for move in child.outgoing_moves:
                    self.assertEqual(move.origin, shipment.outgoing_moves[0])
                    self.assertFalse(move.invoice_lines)
                with config.set_context(locations=[self.warehouse.id]):
                    self.assertEqual(Product(component_a.id).quantity, 0)
                    self.assertEqual(Product(component_b.id).quantity, 10)
                sale.reload()
                self.assertEqual(sum(line.quantity for invoice in sale.invoices
                        for line in invoice.lines if line.type == 'line'), 10)
                self.assertTrue(all(line.product == kit
                        for invoice in sale.invoices for line in invoice.lines
                        if line.type == 'line'))

                # Replenishment delivers the outstanding kits exactly once.
                self.supply(component_a, 10)
                pending, = [s for s in sale.shipments if s.state == 'waiting']
                Wizard('stock.shipment.assign', [pending])
                pending.reload()
                self.assertEqual(pending.state, 'assigned')
                self.finish(pending)
                sale.reload()
                self.assertEqual(sum(m.quantity for s in sale.shipments
                        for m in s.outgoing_moves), 20)
                self.assertEqual(len(sale.kit_component_shipments), 2)
                with config.set_context(locations=[self.warehouse.id]):
                    self.assertEqual(Product(component_a.id).quantity, 0)
                    self.assertEqual(Product(component_b.id).quantity, 0)

                # A voluntary partial is allowed even when all stock exists.
                self.supply(component_a, 10)
                self.supply(component_b, 10)
                voluntary = self.make_sale(kit, 10)
                partial, = voluntary.shipments
                move, = (partial.inventory_moves if separate_output
                    else partial.outgoing_moves)
                move.quantity = 5
                partial.save()
                Wizard('stock.shipment.assign', [partial])
                partial.reload()
                child = self.finish(partial)
                self.assertTrue(all(m.quantity == 5
                        for m in child.outgoing_moves))
                voluntary.reload()
                remaining, = [s for s in voluntary.shipments
                    if s.state == 'waiting']
                self.assertEqual(sum(m.quantity
                        for m in remaining.outgoing_moves), 5)

                # Reset releases reservations and recreates a single auxiliary.
                Wizard('stock.shipment.assign', [remaining])
                remaining.reload()
                remaining.click('wait')
                self.assertEqual(len(remaining.kit_component_shipments), 1)
                remaining.click('cancel')

                # Force remains available when no components can be reserved.
                forced = self.make_sale(kit, 20)
                forced_shipment, = forced.shipments
                force = Wizard('stock.shipment.assign', [forced_shipment])
                self.assertEqual(force.form_state, 'partial')
                force.execute('force')
                forced_shipment.reload()
                self.assertEqual(forced_shipment.state, 'assigned')
                self.finish(forced_shipment)
