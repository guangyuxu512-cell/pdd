import unittest


class ShopCrudTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)

    def test_shop_crud(self) -> None:
        cleanup_res = self.client.get("/api/shops", params={"platform": "taobao"})
        self.assertEqual(cleanup_res.status_code, 200, cleanup_res.text)
        for item in cleanup_res.json():
            if item["shop_id"] == "crud_shop_001":
                self.client.delete(f"/api/shops/{item['id']}")

        create_res = self.client.post(
            "/api/shops",
            json={
                "platform": "taobao",
                "shop_id": "crud_shop_001",
                "shop_name": "CRUD 测试店铺",
                "worker_id": "instance_a",
            },
        )
        self.assertEqual(create_res.status_code, 200, create_res.text)
        created = create_res.json()
        shop_pk = created["id"]
        self.assertEqual(created["shop_id"], "crud_shop_001")
        self.assertTrue(created["profile_path"])

        list_res = self.client.get("/api/shops", params={"platform": "taobao"})
        self.assertEqual(list_res.status_code, 200, list_res.text)
        self.assertTrue(any(item["id"] == shop_pk for item in list_res.json()))

        get_res = self.client.get(f"/api/shops/{shop_pk}")
        self.assertEqual(get_res.status_code, 200, get_res.text)
        self.assertEqual(get_res.json()["shop_name"], "CRUD 测试店铺")

        update_res = self.client.patch(
            f"/api/shops/{shop_pk}",
            json={
                "shop_name": "CRUD 测试店铺-已更新",
                "cookie_status": "valid",
                "enabled": False,
            },
        )
        self.assertEqual(update_res.status_code, 200, update_res.text)
        updated = update_res.json()
        self.assertEqual(updated["shop_name"], "CRUD 测试店铺-已更新")
        self.assertEqual(updated["cookie_status"], "valid")
        self.assertFalse(updated["enabled"])

        delete_res = self.client.delete(f"/api/shops/{shop_pk}")
        self.assertEqual(delete_res.status_code, 204, delete_res.text)

        missing_res = self.client.get(f"/api/shops/{shop_pk}")
        self.assertEqual(missing_res.status_code, 404, missing_res.text)


if __name__ == "__main__":
    unittest.main()
