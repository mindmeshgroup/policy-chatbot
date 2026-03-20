'use client';
import { useRouter } from 'next/navigation';

export default function LoginPage() {
  const router = useRouter();

  return (
    <div className="min-h-screen w-full bg-[linear-gradient(180deg,rgba(205,0,0,1)_0%,rgba(103,0,0,1)_100%)] flex items-center justify-center px-4 py-10">

      {/* White Card */}
      <div className="bg-white rounded-[10px] w-full max-w-[500px] flex flex-col items-center px-10 py-10 shadow-2xl">

        {/* Logo */}
        <img
          src="/latrobe-logo.png"
          alt="Latrobe logo"
          className="w-[160px] object-contain mb-2"
        />

        {/* App Name */}
        <p className="font-bold text-black text-base mb-8">
          PolicyDB Chatbot
        </p>

        {/* Who Are You Card */}
        <div className="w-full bg-[linear-gradient(180deg,rgba(205,0,0,1)_0%,rgba(152,1,1,1)_100%)] rounded-[20px] flex flex-col items-center px-8 py-10 gap-5">

          <p className="font-bold text-white text-xl tracking-wide">
            WHO ARE YOU?
          </p>

          {/* Student Button */}
          <button
            onClick={() => router.push('/chat')}
            type="button"
            className="w-full h-[58px] bg-white rounded-lg font-bold text-black text-base hover:bg-gray-100 transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-white"
          >
            I&apos;M A STUDENT
          </button>

          {/* Staff Button */}
          <button
            onClick={() => router.push('/chat')}
            type="button"
            className="w-full h-[58px] bg-white rounded-lg font-bold text-black text-base hover:bg-gray-100 transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-white"
          >
            I&apos;M A STAFF
          </button>

        </div>

        {/* Footer */}
        <div className="mt-8 flex flex-col items-center">
          <p className="text-sm font-light text-black">Powered by:</p>
          <p className="font-bold text-black text-xl">MindMesh Group.</p>
        </div>

      </div>
    </div>
  );
}