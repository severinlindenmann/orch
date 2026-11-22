// orch Companion, step 5 (ORCH-1195): explain the two Mac permissions before the Mac asks, start with the Mac, and
// update itself. An update is installed only when all of this holds (ORCH-1497): it carries our Apple signature
// (Developer ID, team `ourTeam`, our bundle id) and is notarized; it is newer than the running app (never older);
// every request and every redirect is HTTPS to GitHub. An unsigned (ad-hoc) build never updates itself. The
// signing key lives only in the owner-run release step (release.sh); the helper account can publish GitHub
// releases, so this signature check is the real barrier.

import AppKit
import AVFoundation
import CoreAudio
import Foundation
import Security
import ServiceManagement

let version = (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "0.0.0"
let releasesURL = URL(string: "https://api.github.com/repos/severinlindenmann/orch/releases?per_page=30")!
let releaseTag = "companion-v"
let ourTeam = "77D4THRYUN"  // the Apple team of the phone app; the Developer ID certificate belongs to it
let ourIdentifier = "io.severin.orch.companion"
/// Hosts an update may talk to: the GitHub API, the release page and the hosts GitHub redirects downloads to.
let updateHosts: Set<String> = ["api.github.com", "github.com", "objects.githubusercontent.com",
                                "release-assets.githubusercontent.com"]
let updateEvery = 6.0 * 3600

// MARK: - permissions

enum Permission { case microphone, callSound }

func microphoneAllowed() -> Bool { AVCaptureDevice.authorizationStatus(for: .audio) == .authorized }

func askMicrophone(_ done: @escaping (Bool) -> Void) {
    AVCaptureDevice.requestAccess(for: .audio) { ok in DispatchQueue.main.async { done(ok) } }
}

/// macOS has no public way to read the "Screen & System Audio Recording" answer; making a tap of our own sound
/// once makes the Mac ask. We remember that we asked.
func askCallSound() {
    let mine = audioProcesses().filter { $0.pid == getpid() }.map { $0.object }
    let desc = CATapDescription(stereoMixdownOfProcesses: mine)
    desc.isPrivate = true
    var tap = AudioObjectID(kAudioObjectUnknown)
    if AudioHardwareCreateProcessTap(desc, &tap) == noErr { AudioHardwareDestroyProcessTap(tap) }
    UserDefaults.standard.set(true, forKey: "askedCallSound")
}

let setupTitle = "orch Companion records your calls for Meetings"
let setupIntro = "It records only after you said that everyone on the call agreed. Your Mac asks you two things once:"
let nothingWords = "Nothing is recorded until you say so."
let micWords = "Microphone: so your own voice is in the recording."
let soundWords = "Call sound: so the others in the call are in the recording. "
    + "The Mac calls this Screen and System Audio Recording. "
    + "orch Companion takes only the sound of the call app, never your screen."
let startWords = "Start orch Companion with my Mac"

/// The first-run window, also opened from the menu ("Permissions…").
final class SetupWindow: NSObject {
    var window: NSWindow?
    let micButton = NSButton(title: "Allow microphone", target: nil, action: nil)
    let soundButton = NSButton(title: "Allow call sound", target: nil, action: nil)
    let startBox = NSButton(checkboxWithTitle: startWords, target: nil, action: nil)

    func make() -> NSWindow {
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 300), styleMask: [.titled, .closable],
                         backing: .buffered, defer: false)
        w.title = "orch Companion"
        w.isReleasedWhenClosed = false
        let title = NSTextField(wrappingLabelWithString: setupTitle)
        title.font = .boldSystemFont(ofSize: 15)
        let intro = NSTextField(wrappingLabelWithString: setupIntro)
        micButton.target = self
        micButton.action = #selector(allowMic)
        soundButton.target = self
        soundButton.action = #selector(allowSound)
        startBox.target = self
        startBox.action = #selector(toggleStart)
        let done = NSButton(title: "Done", target: self, action: #selector(close))
        done.keyEquivalent = "\r"
        func row(_ text: String, _ b: NSButton) -> NSView {
            let l = NSTextField(wrappingLabelWithString: text)
            l.preferredMaxLayoutWidth = 290
            let r = NSStackView(views: [l, b])
            r.alignment = .top
            r.distribution = .fill
            return r
        }
        let nothing = NSTextField(wrappingLabelWithString: nothingWords)
        let stack = NSStackView(views: [title, intro, row(micWords, micButton), row(soundWords, soundButton),
                                        nothing, startBox, done])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.edgeInsets = NSEdgeInsets(top: 18, left: 18, bottom: 18, right: 18)
        for v in [title, intro, nothing] { v.preferredMaxLayoutWidth = 420 }
        w.contentView = stack
        refresh()
        return w
    }

    func refresh() {
        let mic = microphoneAllowed()
        micButton.title = mic ? "Allowed" : "Allow microphone"
        micButton.isEnabled = !mic
        let asked = UserDefaults.standard.bool(forKey: "askedCallSound")
        soundButton.title = asked ? "Asked" : "Allow call sound"
        startBox.state = SMAppService.mainApp.status == .enabled ? .on : .off
    }

    func show() {
        if window == nil { window = make() }
        refresh()
        window?.center()
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }

    /// The window as a picture, never shown (for the review card): --render-setup out.png
    func render(to path: String) -> Bool {
        let w = make()
        guard let view = w.contentView else { return false }
        view.appearance = NSAppearance(named: .aqua)
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor(white: 0.93, alpha: 1).cgColor
        micButton.title = "Allow microphone"
        micButton.isEnabled = true
        soundButton.title = "Allow call sound"
        startBox.state = .on
        view.setFrameSize(NSSize(width: 460, height: max(view.fittingSize.height, 300)))
        view.layoutSubtreeIfNeeded()
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return false }
        view.cacheDisplay(in: view.bounds, to: rep)
        guard let png = rep.representation(using: .png, properties: [:]) else { return false }
        return FileManager.default.createFile(atPath: path, contents: png)
    }

    @objc func allowMic() { askMicrophone { [weak self] _ in self?.refresh() } }
    @objc func allowSound() { askCallSound(); refresh() }
    @objc func toggleStart() { setStartWithMac(startBox.state == .on); refresh() }
    @objc func close() { UserDefaults.standard.set(true, forKey: "setupSeen"); window?.close() }
}

// MARK: - start with the Mac

func setStartWithMac(_ on: Bool) {
    do {
        if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
    } catch {
        NSLog("orch Companion: start with the Mac could not be changed: \(error.localizedDescription)")
    }
}

// MARK: - updates

/// "1.2.10" -> [1, 2, 10]; nil unless exactly three plain numbers ("1..2", "+1.0.0", "1.2.3." are nil).
func versionParts(_ s: String) -> [Int]? {
    let p = s.split(separator: ".", omittingEmptySubsequences: false)
    guard p.count == 3 else { return nil }
    var out: [Int] = []
    for x in p {
        guard !x.isEmpty, x.count <= 6, x.allSatisfy({ $0.isASCII && $0.isNumber }), let n = Int(x) else { return nil }
        out.append(n)
    }
    return out
}

/// "1.2.10" > "1.2.9"; false whenever either side is not a plain version (an unknown version never updates).
func newer(_ a: String, than b: String) -> Bool {
    guard let x = versionParts(a), let y = versionParts(b) else { return false }
    return x != y && !x.lexicographicallyPrecedes(y)
}

let maxUpdateBytes: Int64 = 200 * 1024 * 1024

/// From the GitHub releases list: the newest "companion-vX.Y.Z" release (not a draft or pre-release) with its zip.
func pickRelease(_ json: Any) -> (version: String, zip: URL)? {
    guard let rows = json as? [[String: Any]] else { return nil }
    var best: (String, URL)?
    for r in rows {
        guard let tag = r["tag_name"] as? String, tag.hasPrefix(releaseTag),
              r["draft"] as? Bool != true, r["prerelease"] as? Bool != true,
              let assets = r["assets"] as? [[String: Any]] else { continue }
        let v = String(tag.dropFirst(releaseTag.count))
        guard versionParts(v) != nil,
              let a = assets.first(where: { ($0["name"] as? String) == "orch-Companion-\(v).zip" }),
              let u = (a["browser_download_url"] as? String).flatMap(URL.init(string:)),
              allowedUpdateURL(u) else { continue }
        if best == nil || newer(v, than: best!.0) { best = (v, u) }
    }
    return best.map { (version: $0.0, zip: $0.1) }
}

/// The Apple team that signed this running app, or nil for an unsigned (ad-hoc) build.
func myTeam() -> String? {
    var code: SecCode?
    guard SecCodeCopySelf([], &code) == errSecSuccess, let c = code else { return nil }
    var stat: SecStaticCode?
    guard SecCodeCopyStaticCode(c, [], &stat) == errSecSuccess, let s = stat else { return nil }
    var info: CFDictionary?
    guard SecCodeCopySigningInformation(s, SecCSFlags(rawValue: kSecCSSigningInformation), &info) == errSecSuccess,
          let d = info as? [String: Any] else { return nil }
    return d[kSecCodeInfoTeamIdentifier as String] as? String
}

/// Only HTTPS to GitHub, for the release list, the download and every redirect in between.
func allowedUpdateURL(_ u: URL?) -> Bool {
    guard let u, u.scheme == "https", let h = u.host?.lowercased() else { return false }
    return updateHosts.contains(h) && (u.port == nil || u.port == 443) && u.user == nil
}

/// The code requirement a downloaded app must meet: Developer ID (not a development or App Store certificate),
/// the given team and bundle id, notarized by Apple.
func updateRequirement(identifier: String = ourIdentifier, team: String = ourTeam) -> String {
    "identifier \"\(identifier)\" and anchor apple generic"
        + " and certificate 1[field.1.2.840.113635.100.6.2.6] exists"
        + " and certificate leaf[field.1.2.840.113635.100.6.1.13] exists"
        + " and certificate leaf[subject.OU] = \"\(team)\" and notarized"
}

/// True when the app at `url` is validly signed and meets `updateRequirement`.
func signedByUs(_ url: URL, identifier: String = ourIdentifier, team: String = ourTeam) -> Bool {
    var stat: SecStaticCode?
    guard SecStaticCodeCreateWithPath(url as CFURL, [], &stat) == errSecSuccess, let s = stat else { return false }
    var r: SecRequirement?
    let req = updateRequirement(identifier: identifier, team: team)
    guard SecRequirementCreateWithString(req as CFString, [], &r) == errSecSuccess else { return false }
    let flags = SecCSFlags(rawValue: kSecCSCheckAllArchitectures | kSecCSStrictValidate | kSecCSCheckNestedCode)
    return SecStaticCodeCheckValidity(s, flags, r) == errSecSuccess
}

/// Refuses any redirect that leaves HTTPS to GitHub.
final class GitHubOnly: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(allowedUpdateURL(request.url) ? request : nil)
    }
}

let updateSession: URLSession = {
    let c = URLSessionConfiguration.ephemeral
    c.tlsMinimumSupportedProtocolVersion = .TLSv12
    return URLSession(configuration: c, delegate: GitHubOnly(), delegateQueue: nil)
}()

/// The version inside a downloaded app (after its signature was checked, so the Info.plist is sealed).
func bundleVersion(_ app: URL) -> String? {
    // read the file itself: Bundle(url:) caches by path and would still show the replaced app's version
    let plist = app.appendingPathComponent("Contents/Info.plist")
    return (NSDictionary(contentsOf: plist)?["CFBundleShortVersionString"]) as? String
}

final class Updater {
    var timer: Timer?
    var status = "Updates: checking"
    var onStatus: ((String) -> Void)?
    var busy: () -> Bool = { false }  // during a call nothing is installed (it would end the recording)
    /// One look or install at a time, and none after an install (so an older release can never follow a newer one).
    private let lock = NSLock()
    private var running = false
    private var installed = false

    func begin() -> Bool {
        lock.lock(); defer { lock.unlock() }
        if running || installed { return false }
        running = true
        return true
    }

    func end(installed done: Bool = false) {
        lock.lock(); running = false; if done { installed = true }; lock.unlock()
    }

    func start() {
        guard myTeam() == ourTeam, versionParts(version) != nil, allowedUpdateURL(releasesURL) else {
            status = "Updates: only for the signed app"; return
        }
        check()
        timer = Timer.scheduledTimer(withTimeInterval: updateEvery, repeats: true) { [weak self] _ in self?.check() }
    }

    func say(_ s: String) { DispatchQueue.main.async { self.status = s; self.onStatus?(s) } }

    func check() {
        guard myTeam() == ourTeam, allowedUpdateURL(releasesURL), begin() else { return }
        if busy() { end(); say("Updates: waiting until the call ends"); return }
        var req = URLRequest(url: releasesURL)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.setValue("orch-companion/\(version)", forHTTPHeaderField: "User-Agent")
        updateSession.dataTask(with: req) { [weak self] data, resp, _ in
            guard let self, allowedUpdateURL(resp?.url), (resp as? HTTPURLResponse)?.statusCode == 200,
                  let data, let json = try? JSONSerialization.jsonObject(with: data),
                  let rel = pickRelease(json) else { self?.end(); self?.say("Updates: could not look"); return }
            guard newer(rel.version, than: version) else { self.end(); self.say("Up to date (\(version))"); return }
            self.install(rel.zip, version: rel.version)
        }.resume()
    }

    func install(_ zip: URL, version v: String) {
        guard allowedUpdateURL(zip) else { end(); say("Updates: not from GitHub, not installed"); return }
        updateSession.downloadTask(with: zip) { [weak self] file, resp, _ in
            guard let self else { return }
            var ok = false
            defer { if !ok { self.end() } }
            let size = (try? file?.resourceValues(forKeys: [.fileSizeKey]).fileSize).flatMap { $0 }.map(Int64.init)
            guard let file, allowedUpdateURL(resp?.url), (resp as? HTTPURLResponse)?.statusCode == 200,
                  let size, size > 0, size <= maxUpdateBytes
            else { self.say("Updates: download failed"); return }
            let fm = FileManager.default
            let dir = fm.temporaryDirectory.appendingPathComponent("orch-companion-\(UUID())")
            guard (try? fm.createDirectory(at: dir, withIntermediateDirectories: false,
                                           attributes: [.posixPermissions: 0o700])) != nil else {
                self.say("Updates: could not unpack"); return
            }
            let unzip = Process()
            unzip.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
            unzip.arguments = ["-x", "-k", file.path, dir.path]
            try? unzip.run()
            unzip.waitUntilExit()
            let app = dir.appendingPathComponent("orch Companion.app")
            defer { try? FileManager.default.removeItem(at: dir) }
            let isDir = (try? app.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey]))
                .map { $0.isDirectory == true && $0.isSymbolicLink != true } ?? false
            guard unzip.terminationStatus == 0, isDir, signedByUs(app) else {
                self.say("Updates: the download was not signed by us, not installed")
                return
            }
            // never an older or a different version than the release says (no rollback)
            guard let got = bundleVersion(app), got == v, newer(got, than: version) else {
                self.say("Updates: the download is not the newer version, not installed")
                return
            }
            if DispatchQueue.main.sync(execute: { self.busy() }) {
                self.say("Updates: waiting until the call ends")
                return
            }
            do {
                _ = try FileManager.default.replaceItemAt(Bundle.main.bundleURL, withItemAt: app)
            } catch {
                self.say("Updates: could not replace the app")
                return
            }
            // the app now in place must still be ours and the newer version before it is started
            guard signedByUs(Bundle.main.bundleURL), bundleVersion(Bundle.main.bundleURL) == v else {
                self.say("Updates: the installed app failed its check, not started")
                return
            }
            ok = true
            self.end(installed: true)
            self.say("Updated to \(v), starting again")
            DispatchQueue.main.async {
                let again = Process()
                again.executableURL = URL(fileURLWithPath: "/usr/bin/open")
                again.arguments = ["-n", Bundle.main.bundleURL.path]
                try? again.run()
                NSApp.terminate(nil)
            }
        }.resume()
    }
}

func updaterSelftest() -> Int {
    var failed = 0
    for (a, b, want) in [("1.2.10", "1.2.9", true), ("1.2.9", "1.2.10", false), ("1.0.0", "1.0.0", false),
                         ("2.0.0", "1.9.9", true), ("x", "0.0.1", false), ("1.2.3", "x", false),
                         ("1..2.3", "0.0.1", false), ("+1.0.0", "0.0.1", false), ("1.2.3.", "0.0.1", false),
                         ("1.2", "0.0.1", false), ("１.0.0", "0.0.1", false)] {
        if newer(a, than: b) != want { failed += 1; print("FAIL newer(\(a), \(b))") }
    }
    let rel: [[String: Any]] = [
        ["tag_name": "companion-v0.2.0", "draft": false, "prerelease": false, "assets": [
            ["name": "orch-Companion-0.2.0.zip", "browser_download_url": "https://github.com/x/releases/a.zip"]]],
        ["tag_name": "companion-v0.3.0", "draft": false, "prerelease": true, "assets": [
            ["name": "orch-Companion-0.3.0.zip", "browser_download_url": "https://github.com/x/releases/b.zip"]]],
        ["tag_name": "companion-v0.2.5", "draft": false, "prerelease": false, "assets": [
            ["name": "orch-Companion-0.2.5.zip", "browser_download_url": "http://evil.example/c.zip"]]],
        ["tag_name": "v9.9.9", "assets": []],
    ]
    if pickRelease(rel)?.version != "0.2.0" { failed += 1; print("FAIL pickRelease") }
    for (u, want) in [("https://github.com/severinlindenmann/orch/releases/download/companion-v1.0.0/a.zip", true),
                      ("https://objects.githubusercontent.com/x", true),
                      ("https://release-assets.githubusercontent.com/x", true),
                      ("https://api.github.com/repos/x/releases", true),
                      ("http://github.com/x.zip", false), ("https://github.com.evil.example/x.zip", false),
                      ("https://evil.example/github.com/x.zip", false), ("https://github.com:8443/x.zip", false),
                      ("https://user@github.com/x.zip", false), ("file:///tmp/x.zip", false)] {
        if allowedUpdateURL(URL(string: u)) != want { failed += 1; print("FAIL allowedUpdateURL(\(u))") }
    }
    if allowedUpdateURL(nil) { failed += 1; print("FAIL allowedUpdateURL(nil)") }
    // an ad-hoc signed copy of this very app is never accepted as an update
    if signedByUs(Bundle.main.bundleURL) && myTeam() != ourTeam { failed += 1; print("FAIL unsigned accepted") }
    print(failed == 0 ? "ok   updates pick the newest signed-for release" : "FAIL updates")
    return failed
}
