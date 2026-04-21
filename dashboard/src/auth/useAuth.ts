import { useMsal, useIsAuthenticated } from "@azure/msal-react";
import { loginRequest, isMsalConfigured } from "./msalConfig";

interface AuthReturn {
  isAuthenticated: boolean;
  login: () => Promise<void>;
  logout: () => void;
  getAccessToken: () => Promise<string | null>;
  user: { name: string; email: string } | null;
}

export function useAuth(): AuthReturn {
  if (!isMsalConfigured) {
    return {
      isAuthenticated: true,
      login: async () => {},
      logout: () => {},
      getAccessToken: async () => null,
      user: { name: "Local Dev", email: "" },
    };
  }

  const { instance, accounts } = useMsal();
  const isAuthenticated = useIsAuthenticated();
  const account = accounts[0] || null;

  return {
    isAuthenticated,
    login: async () => {
      await instance.loginRedirect(loginRequest);
    },
    logout: () => {
      instance.logoutRedirect({ postLogoutRedirectUri: window.location.origin + "/dashboard/" });
    },
    getAccessToken: async () => {
      if (!account) return null;
      try {
        const resp = await instance.acquireTokenSilent({
          ...loginRequest,
          account,
        });
        return resp.idToken;
      } catch {
        await instance.acquireTokenRedirect(loginRequest);
        return null;
      }
    },
    user: account
      ? {
          name: account.name || account.username,
          email: account.username,
        }
      : null,
  };
}
