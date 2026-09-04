import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from jarvis_bambu.excel_report import MANDATORY_PRICE_COLUMNS, PRICE_COLUMNS
from jarvis_bambu.models import PieceMetrics
from jarvis_bambu.price_analysis import (
    GlobalPriceOptions, PriceAnalysisItem, PriceAnalysisResult, analyze_price_files,
    export_price_analysis, inspect_price_file, item_final_price,
    recalculate_price_totals,
)


def make_stl(folder, name="piece.stl"):
    path=Path(folder)/name; path.write_text("solid p\nendsolid p\n",encoding="ascii"); return path


def make_3mf(folder, name="project.3mf"):
    path=Path(folder)/name
    model='<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources/><build><item objectid="1"/><item objectid="2"/></build></model>'
    with zipfile.ZipFile(path,"w") as archive: archive.writestr("3D/3dmodel.model",model)
    return path


def metrics(path, grams=100, minutes=120):
    return PieceMetrics(path,minutes,grams,None,"P2S","PLA","Standard")


class PriceAnalysisCoreTests(unittest.TestCase):
    def test_stl_and_3mf_light_import(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(inspect_price_file(make_stl(folder)),1)
            self.assertEqual(inspect_price_file(make_3mf(folder)),2)

    def test_multipliers_and_quantity_are_combined_once(self):
        with tempfile.TemporaryDirectory() as folder:
            item=PriceAnalysisItem(make_stl(folder),quantity=3,price_multiplier=1.5); item.metrics=metrics(item.path)
            options=GlobalPriceOptions(global_multiplier=1.2)
            # base=(100*.0115*3)+(2*.2)=3.85; total=3.85*3*1.5*1.2
            self.assertAlmostEqual(item_final_price(item,options),20.79)
            totals=recalculate_price_totals([item],options)
            self.assertEqual(totals.units,3); self.assertEqual(totals.weight_grams,300)
            self.assertAlmostEqual(totals.final_price,20.79)

    def test_one_file_error_does_not_cancel_others(self):
        with tempfile.TemporaryDirectory() as folder:
            first=PriceAnalysisItem(make_stl(folder,"bad.stl")); second=PriceAnalysisItem(make_stl(folder,"good.stl"))
            def processor(path):
                if path.name=="bad.stl": raise ValueError("broken")
                return metrics(path)
            result=analyze_price_files([first,second],GlobalPriceOptions(),processor=processor)
            self.assertEqual((first.state,second.state),("error","analyzed")); self.assertEqual(len(result.warnings),1)

    def test_excel_visibility_formula_and_template_style(self):
        with tempfile.TemporaryDirectory() as folder:
            path=make_stl(folder); item=PriceAnalysisItem(path,quantity=2,price_multiplier=1.5); item.metrics=metrics(path)
            options=GlobalPriceOptions(global_multiplier=1.25,visible_categories=["name","quantity","final_price"])
            result=PriceAnalysisResult([item],recalculate_price_totals([item],options),[],0)
            output=Path(folder)/"prices.xlsx"
            export_price_analysis(result,options,output,Path("Plantilla_Analisis_Piezas.xlsx").resolve())
            workbook=load_workbook(output,data_only=False); sheet=workbook["Analisis"]
            self.assertEqual(sheet["P5"].value,2); self.assertEqual(sheet["Q5"].value,1.5); self.assertEqual(sheet["R5"].value,1.25); self.assertEqual(sheet["S5"].value,"=L5*P5*Q5*R5")
            self.assertFalse(sheet.column_dimensions["B"].hidden); self.assertTrue(sheet.column_dimensions["I"].hidden)
            self.assertIsNotNone(sheet["A1"].fill); self.assertEqual(sheet.freeze_panes,"A5")

    def test_mandatory_name_cannot_be_hidden(self):
        self.assertIn("name",MANDATORY_PRICE_COLUMNS); self.assertIn("name",PRICE_COLUMNS)


if __name__=="__main__": unittest.main()
