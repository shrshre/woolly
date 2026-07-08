import { useAuth } from "../auth/AuthContext";
import { AuthForm } from "./AuthForm";

export function Login() {
  const { login } = useAuth();
  return (
    <AuthForm
      title="Welcome back"
      submitLabel="Log in"
      onSubmit={login}
      altText="New to Woolly?"
      altLinkText="Create an account"
      altLinkTo="/signup"
    />
  );
}
