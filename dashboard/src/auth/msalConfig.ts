import { PublicClientApplication, LogLevel } from "@azure/msal-browser";

const clientId = import.meta.env.VITE_AZURE_CLIENT_ID || "d10a5d3c-eee5-41f8-8955-6c587b14bb70";
const tenantId = import.meta.env.VITE_AZURE_TENANT_ID || "5df6d88f-0d78-491b-9617-8b43a209ba73";

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
  scopes: ["openid", "profile", "email"],
};

export const msalInstance = new PublicClientApplication(msalConfig);

export const isMsalConfigured = Boolean(clientId && tenantId);
