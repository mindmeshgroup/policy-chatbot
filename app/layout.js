import '@fontsource/dm-sans/400.css';
import '@fontsource/dm-sans/700.css';
import "./globals.css";

export const metadata = {
  title: "PolicyDB Chatbot",
  description: "La Trobe University Policy Chatbot by MindMesh Group",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        {children}
      </body>
    </html>
  );
}