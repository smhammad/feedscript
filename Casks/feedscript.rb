cask "feedscript" do
  version "0.1.1"
  sha256 "555cc0f94eccf4e3244190a7e88aa18f509c311e495ea3773064cb9aa1c76673"

  url "https://github.com/smhammad/feedscript/releases/download/v#{version}/Feedscript-macOS.zip"
  name "Feedscript"
  desc "Local-first desktop app for bulk transcription of short-form video content"
  homepage "https://github.com/smhammad/feedscript"

  livecheck do
    url :url
    strategy :github_latest
  end

  app "Feedscript.app"

  zap trash: [
    "~/Library/Application Support/Feedscript",
    "~/Library/Logs/Feedscript",
    "~/.cache/whisper",
  ]
end
