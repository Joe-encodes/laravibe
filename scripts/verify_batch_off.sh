#!/bin/bash
# scripts/verify_batch_off.sh
# Switches to Boost OFF and runs evaluation.

# 1. Switch Boost OFF in manifest
sed -i 's/use_boost_context: true/use_boost_context: false/' batch_manifest.yaml
sed -i 's/batch_report_boost_on.csv/batch_report_boost_off.csv/' batch_manifest.yaml

# 2. Run the batch
bash scripts/verify_batch.sh

# 3. Switch Boost back ON for safety
sed -i 's/use_boost_context: false/use_boost_context: true/' batch_manifest.yaml
sed -i 's/batch_report_boost_off.csv/batch_report_boost_on.csv/' batch_manifest.yaml
