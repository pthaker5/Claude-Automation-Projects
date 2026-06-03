#!/bin/bash
# ============================================================
# DC&E Billing Audit — Azure Deployment Script
# Mirrors ai-automation_ap-remittance deployment pattern.
# Run from Azure Cloud Shell or local az CLI (logged in).
# ============================================================

if [ -f .env ]; then
  set -a; source .env; set +a
  echo "Loaded configuration from .env"
else
  echo "ERROR: .env file not found. Copy .env.example to .env and fill in values."
  exit 1
fi

echo "==> Setting subscription to $SUBSCRIPTION_NAME ($SUBSCRIPTION_ID)"
az account set --subscription "$SUBSCRIPTION_ID"

APP_SERVICE_PLAN="${APP_SERVICE_PLAN:-plan-dce-billing-audit}"
WEB_APP_NAME="${WEB_APP_NAME:-quantix-dce-billing-audit}"
ZIP_PATH="dce_billing_audit_deploy.zip"
FLASK_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# ============================================================
echo "==> Step 0: Build deployment ZIP"
rm -f "$ZIP_PATH"
zip -r "$ZIP_PATH" \
  app.py sql_client.py requirements.txt startup.txt \
  static/ templates/ \
  -x "*.pyc" "__pycache__/*" ".env" ".env.*" "*.sh" "data/*"
echo "    Created $ZIP_PATH ($(du -h "$ZIP_PATH" | cut -f1))"

# ============================================================
echo "==> Step 1: Create resource group (or verify existing)"
az group create \
  --name $RESOURCE_GROUP \
  --location $LOCATION

# ============================================================
echo "==> Step 2: Create App Service plan (or verify existing)"
az appservice plan create \
  --name $APP_SERVICE_PLAN \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku B1 \
  --is-linux

# ============================================================
echo "==> Step 3: Create or update Web App (Python 3.11)"
if az webapp show --name $WEB_APP_NAME --resource-group $RESOURCE_GROUP &>/dev/null; then
  echo "    Web app '$WEB_APP_NAME' already exists — skipping creation."
else
  echo "    Creating web app '$WEB_APP_NAME'..."
  az webapp create \
    --name $WEB_APP_NAME \
    --resource-group $RESOURCE_GROUP \
    --plan $APP_SERVICE_PLAN \
    --runtime "PYTHON:3.11"
fi

# ============================================================
echo "==> Step 4: Configure app settings"
az webapp config appsettings set \
  --name $WEB_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
    EDW_SP_TENANT_ID="$EDW_SP_TENANT_ID" \
    EDW_SP_CLIENT_ID="$EDW_SP_CLIENT_ID" \
    EDW_SP_CLIENT_SECRET="$EDW_SP_CLIENT_SECRET" \
    EDW_DEV_SERVER="$EDW_DEV_SERVER" \
    EDW_DEV_DB="$EDW_DEV_DB" \
    FLASK_SECRET_KEY="$FLASK_SECRET_KEY" \
    SCM_DO_BUILD_DURING_DEPLOYMENT=true \
    WEBSITES_CONTAINER_START_TIME_LIMIT=300

# ============================================================
echo "==> Step 5: Set startup command"
az webapp config set \
  --name $WEB_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --startup-file "gunicorn --bind=0.0.0.0:8000 --workers=2 --timeout=600 app:app"

# ============================================================
echo "==> Step 6: Configure Easy Auth (Microsoft identity provider)"
az webapp auth update \
  --name $WEB_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --enabled true \
  --action RedirectToLoginPage \
  --aad-allowed-token-audiences "api://$EASYAUTH_CLIENT_ID" \
  --aad-client-id "$EASYAUTH_CLIENT_ID" \
  --aad-client-secret "$EASYAUTH_CLIENT_SECRET" \
  --aad-token-issuer-url "https://sts.windows.net/$EDW_SP_TENANT_ID/v2.0"

# ============================================================
echo "==> Step 7: Deploy from ZIP (with Oryx build for pip install)"
az webapp deployment source config-zip \
  --name $WEB_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --src $ZIP_PATH

# ============================================================
echo "==> Step 8: Restart app"
az webapp restart \
  --name $WEB_APP_NAME \
  --resource-group $RESOURCE_GROUP

# ============================================================
echo ""
echo "✅ Deployment complete."
echo "   URL: https://$WEB_APP_NAME.azurewebsites.net"
echo ""
echo "⚠️  Notes:"
echo "   1. Easy Auth configured — verify in Portal: Authentication > 'Require authentication'"
echo "   2. ODBC Driver 18 is pre-installed on Azure App Service Linux (Python 3.11 image)"
echo "   3. gunicorn timeout set to 600s to handle large EDW pulls"
echo "   4. The EDW pull can take 2-5 minutes for a full week's data"
