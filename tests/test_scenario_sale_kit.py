import unittest
from decimal import Decimal

from proteus import Model, Wizard
from trytond.modules.account.tests.tools import (create_chart,
                                                 create_fiscalyear, create_tax,
                                                 get_accounts)
from trytond.modules.account_invoice.tests.tools import (
    create_payment_term, set_fiscalyear_invoice_sequences)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):

        # Install sale_kit
        activate_modules('sale_kit')

        # Create company
        _ = create_company()
        company = get_company()

        # Create fiscal year
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company))
        fiscalyear.click('create_period')

        # Create chart of accounts
        _ = create_chart(company)
        accounts = get_accounts(company)
        revenue = accounts['revenue']
        expense = accounts['expense']

        # Create tax
        tax = create_tax(Decimal('.10'))
        tax.save()

        # Create parties
        Party = Model.get('party.party')
        supplier = Party(name='Supplier')
        supplier.save()
        customer = Party(name='Customer')
        customer.save()

        # Create account category
        ProductCategory = Model.get('product.category')
        account_category = ProductCategory(name="Account Category")
        account_category.accounting = True
        account_category.account_expense = expense
        account_category.account_revenue = revenue
        account_category.customer_taxes.append(tax)
        account_category.save()

        # Create product
        ProductUom = Model.get('product.uom')
        unit, = ProductUom.find([('name', '=', 'Unit')])
        meter, = ProductUom.find([('name', '=', 'Meter')])
        ProductTemplate = Model.get('product.template')
        ProductKitLine = Model.get('product.kit.line')
        tkit1 = ProductTemplate()
        tkit1.name = 'product'
        tkit1.default_uom = unit
        tkit1.type = 'goods'
        tkit1.salable = True
        tkit1.list_price = Decimal('10')
        tkit1.cost_price_method = 'fixed'
        tkit1.account_category = account_category
        pkit1, = tkit1.products
        pkit1.cost_price = Decimal('5')
        tkit1.save()
        pkit1, = tkit1.products
        tkit2 = ProductTemplate()
        tkit2.name = 'product'
        tkit2.default_uom = unit
        tkit2.type = 'goods'
        tkit2.salable = True
        tkit2.list_price = Decimal('10')
        tkit2.cost_price_method = 'fixed'
        tkit2.account_category = account_category
        pkit2, = tkit2.products
        pkit2.cost_price = Decimal('5')
        tkit2.save()
        pkit2, = tkit2.products
        tkit3 = ProductTemplate()
        tkit3.name = 'product'
        tkit3.default_uom = meter
        tkit3.type = 'goods'
        tkit3.salable = True
        tkit3.list_price = Decimal('10')
        tkit3.cost_price_method = 'fixed'
        tkit3.account_category = account_category
        pkit3, = tkit3.products
        pkit3.cost_price = Decimal('5')
        tkit3.save()
        pkit3, = tkit3.products
        template = ProductTemplate()
        template.name = 'product'
        template.default_uom = unit
        template.type = 'goods'
        template.salable = True
        template.list_price = Decimal('10')
        template.cost_price_method = 'fixed'
        template.account_category = account_category
        product, = template.products
        product.cost_price = Decimal('5')
        product.kit = True
        product.explode_kit_in_sales = True
        template.save()
        product, = template.products
        pkit_line1 = ProductKitLine()
        product.kit_lines.append(pkit_line1)
        pkit_line1.product = pkit1
        pkit_line1.quantity = 1
        pkit_line2 = ProductKitLine()
        product.kit_lines.append(pkit_line2)
        pkit_line2.product = pkit2
        pkit_line2.quantity = 1
        pkit_line3 = ProductKitLine()
        product.kit_lines.append(pkit_line3)
        pkit_line3.product = pkit3
        pkit_line3.quantity = 1
        product.save()

        # Create payment term
        payment_term = create_payment_term()
        payment_term.save()

        # Sale products
        Sale = Model.get('sale.sale')
        SaleLine = Model.get('sale.line')
        sale = Sale()
        sale.party = customer
        sale.payment_term = payment_term
        sale.invoice_method = 'order'
        sale_line = SaleLine()
        sale.lines.append(sale_line)
        sale_line.product = product
        sale_line.quantity = 2.0
        sale.save()
        sale.click('quote')
        self.assertEqual(len(sale.lines), 4)

        line1, line2, line3, line4 = sale.lines
        self.assertEqual(line1.kit_depth, 0)
        self.assertEqual(line2.kit_depth, 1)
        self.assertEqual(line3.kit_depth, 1)
        self.assertEqual(line4.kit_depth, 1)

        # Return a sale
        return_sale = Wizard('sale.return_sale', [sale])
        return_sale.execute('return_')
        returned_sale, = Sale.find([
            ('state', '=', 'draft'),
        ])
        self.assertEqual(len(returned_sale.lines), 4)

        line1, line2, line3, line4 = returned_sale.lines
        self.assertEqual(line1.product.kit, True)
        self.assertEqual(line1.unit_price, Decimal('10.0000'))
        self.assertEqual(line2.unit_price, Decimal('0.0'))
        self.assertEqual(line3.unit_price, Decimal('0.0'))
        self.assertEqual(line4.unit_price, Decimal('0.0'))
