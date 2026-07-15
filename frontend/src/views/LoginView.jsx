import { useAuth } from "../authContext";

export default function LoginView() {
  const { signIn } = useAuth();

  return (
    <div className="login-screen">
      <div className="login-card">
        <h1>🚴 Training Dashboard</h1>
        <p className="caption">Sign in to see your training data.</p>
        <button className="primary-btn" onClick={() => signIn().catch((e) => alert(e.message))}>
          Sign in with Google
        </button>
      </div>
    </div>
  );
}
