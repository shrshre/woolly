import { useAuth } from "../auth/AuthContext";
import { AuthForm } from "./AuthForm";

export function SignUp() {
  const { register } = useAuth();
  return (
    <AuthForm
      title="Create your account"
      submitLabel="Sign up"
      onSubmit={register}
      altText="Already have an account?"
      altLinkText="Log in"
      altLinkTo="/login"
    />
  );
}
