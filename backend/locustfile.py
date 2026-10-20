from locust import HttpUser, task, between


class InsightFlowUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def get_dataset_schema(self):
        dataset_id = 4

        with self.client.get(
            f"/datasets/{dataset_id}/schema",
            name="/datasets/[id]/schema",
            catch_response=True,
        ) as response:

            if response.status_code != 200:
                response.failure(
                    f"Schema request failed: HTTP {response.status_code}"
                )