#!/usr/bin/env python
#This file is part sale_kit module for Tryton.
#The COPYRIGHT file at the top level of this repository contains 
#the full copyright notices and license terms.

import os
import sys
import unittest

DIR = os.path.abspath(os.path.normpath(os.path.join(__file__,
    '..', '..', '..', '..', '..', 'trytond')))
if os.path.isdir(DIR):
    sys.path.insert(0, os.path.dirname(DIR))

from trytond.tests.test_tryton import test_view, test_depends
import trytond.tests.test_tryton


class SaleKitTestCase(unittest.TestCase):
    '''
    Test Sale Kit module.
    '''

    def setUp(self):
        trytond.tests.test_tryton.install_module('sale_kit')

    def test0005views(self):
        '''
        Test views.
        '''
        test_view('sale_kit')

    def test0006depends(self):
        '''
        Test depends.
        '''
        test_depends()


def suite():
    suite = trytond.tests.test_tryton.suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        SaleKitTestCase))
    return suite

if __name__ == '__main__':
    unittest.TextTestRunner(verbosity=2).run(suite())
