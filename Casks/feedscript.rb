cask "feedscript" do
  version "0.1.2"
  sha256 "faa4dbeb32153ffdfe91c66af1744c2dba06e1a7d42627a3f0a42411d7c7025b"

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
