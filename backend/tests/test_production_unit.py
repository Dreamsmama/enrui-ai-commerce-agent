import unittest
from types import SimpleNamespace

from app.api.production import _diff
from app.api.templates import _parameterize, _resolve
from app.services.quality_pipeline import apply_generation_controls, validate_and_rewrite_prompt
from app.services.image_postprocess import product_foreground_mask
from PIL import Image, ImageDraw
from app.api.quality import _rules


class ProductionUnitTests(unittest.TestCase):
    def test_template_variables_round_trip(self):
        product = SimpleNamespace(name="测试精华", brand_name="品牌A", category="精华", description="补水", target_users="干皮", ingredients="透明质酸", usage_method="早晚使用", specifications="30ml")
        source = "品牌A测试精华，30ml，核心卖点补水"
        template = _parameterize(source, product)
        self.assertIn("{{product_name}}", template)
        self.assertIn("{{specifications}}", template)
        self.assertEqual(_resolve(template, product), source)

    def test_snapshot_diff_detects_content_and_image(self):
        old = {"modules": [{"id": 1, "title": "首屏", "image_url": "a.png"}]}
        new = {"modules": [{"id": 1, "title": "产品首屏", "image_url": "b.png"}, {"id": 2, "title": "成分"}]}
        result = _diff(old, new)
        self.assertEqual(result["change_count"], 2)
        self.assertEqual(result["changes"][0]["type"], "changed")
        self.assertEqual(result["changes"][1]["type"], "added")

    def test_generation_controls_protect_product_and_limit_variation(self):
        checked = validate_and_rewrite_prompt("为商品做一张首屏", "首屏", [{"id": 1}])
        prompt = apply_generation_controls(checked["corrected"], "strict", "lighting", "preview")
        self.assertIn("严格锁定商品", prompt)
        self.assertIn("仅变化布光和阴影", prompt)
        self.assertIn("快速预览阶段", prompt)
        self.assertIn("保持Logo位置与形状", prompt)

    def test_product_mask_separates_clean_background(self):
        image=Image.new("RGB",(100,100),"white");ImageDraw.Draw(image).rectangle((30,20,70,80),fill="black")
        mask=product_foreground_mask(image)
        self.assertLess(mask.getpixel((5,5)),10)
        self.assertGreater(mask.getpixel((50,50)),240)

    def test_category_quality_rules_extend_general_rules(self):
        rules=_rules("气垫")
        self.assertGreaterEqual(rules["thresholds"]["hero"],85)
        self.assertTrue(any("镜面包装" in item for item in rules["rules"]))


if __name__ == "__main__":
    unittest.main()
