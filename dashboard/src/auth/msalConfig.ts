import { PublicClientApplication, LogLevel } from "@azure/msal-browser";

const clientId = import.meta.env.VITE_AZURE_CLIENT_ID || "";
const tenantId = import.meta.env.VITE_AZURE_TENANT_ID || "";

export const msalConfig = {
  auth: {
    clientId,
    authority: tenantId
      ? `https://login.microsoftonline.com/${tenantId}`
      : undefined,
    redirectUri: window.location.origin + "/dashboard/",
  },
  cache: { cacheLocation: "sessionStorage" as const },
  system: {
    loggerOptions: {
      logLevel: LogLevel.Warning,
      loggerCallback: () => {},
    },
  },
};

export const loginRequest = {
  scopes: clientId ? [`api://${clientId}/Dashboard.Read`] : [],
};

export const msalInstance = new PublicClientApplication(msalConfig);

export const isMsalConfigured = Boolean(clientId && tenantId);
