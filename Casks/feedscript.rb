cask "feedscript" do
  version "0.1.3"
  sha256 "cb8d6c64442749b93a9f95a08c75ea214e946b3142e1e7c6a459d5145bb20c04"

  url "https://github.com/smhammad/feedscript/releases/download/v#{version}/Feedscript-macOS.zip"
  name "Feedscript"
  desc "Local-first desktop app for bulk transcription of short-form video content"
  homepage "https://github.com/smhammad/feedscript"

  livecheck do
    url :url
    strategy :github_latest
  end

  app "Feedscript.app"

  # ~/.cache/whisper is deliberately not zapped: the model cache is shared
  # with every other Whisper tool on the machine, and is not ours to delete.
  zap trash: [
    "~/Library/Application Support/Feedscript",
    "~/Library/Logs/Feedscript",
  ]
end
