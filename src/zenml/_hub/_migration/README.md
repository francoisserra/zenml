# ZenML Hub Integration Migration Workflow

1. Define the plugins you want to add/update in `migration_config.yaml`
2. Run `python src/zenml/_hub/_migration/migrate_to_hub.py`
   - This creates a new `submit_config.yaml`
   - This creates a new commit in the 
   [zenml-hub-plugins repo](https://github.com/zenml-io/zenml-hub-plugins)
3. Login to the ZenML Hub as admin user: `zenml hub login -e sre@zenml.io`
4. Batch-submit the plugins to the hub: `zenml hub submit-batch src/zenml/_hub/_migration/submit_config.yaml`
5. Make sure all the submissions were successful
   - Use `zenml hub list --mine -a` to get a list of all admin plugins (including the failed ones)
   - If a plugin failed, use `zenml hub logs PLUGIN_NAME` to find out why