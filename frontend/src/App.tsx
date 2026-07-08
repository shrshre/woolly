import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { SavedPatternsProvider } from "./auth/SavedPatternsContext";
import { Nav } from "./components/Nav";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { GridMaker } from "./pages/GridMaker";
import { Home } from "./pages/Home";
import { Library } from "./pages/Library";
import { Login } from "./pages/Login";
import { Projects } from "./pages/Projects";
import { SignUp } from "./pages/SignUp";
import { StitchCounter } from "./pages/StitchCounter";

export default function App() {
  return (
    <AuthProvider>
      <SavedPatternsProvider>
        <BrowserRouter>
        <Nav />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/grid-maker" element={<GridMaker />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<SignUp />} />
          <Route
            path="/library"
            element={
              <ProtectedRoute>
                <Library />
              </ProtectedRoute>
            }
          />
          <Route
            path="/projects"
            element={
              <ProtectedRoute>
                <Projects />
              </ProtectedRoute>
            }
          />
          <Route
            path="/counter"
            element={
              <ProtectedRoute>
                <StitchCounter />
              </ProtectedRoute>
            }
          />
        </Routes>
        <div className="divider"></div>
        <footer className="footer">
          Pattern data courtesy of{" "}
          <a href="https://www.ravelry.com" target="_blank" rel="noopener noreferrer">
            Ravelry
          </a>
          . All patterns link back to their designers.
        </footer>
        </BrowserRouter>
      </SavedPatternsProvider>
    </AuthProvider>
  );
}
