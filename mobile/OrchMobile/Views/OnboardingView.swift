import SwiftUI
import UIKit

struct OnboardingView: View {
    @Environment(AppModel.self) private var model
    @State private var showLink = false
    @State private var showScanner = false
    @State private var link = ""
    @State private var linkError: String?
    @State private var finishing = false

    @Environment(\.dynamicTypeSize) private var dynamicType  // re-evaluate fonts when text size changes (no view-identity reset)
    var body: some View {
        let _ = dynamicType
        GeometryReader { geometry in
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    OrbitMark().frame(width: 42, height: 42)
                    if model.phase == .notifyStep {
                        ScreenHeading(title: "You're connected.", subtitle: model.pairedWorkspaces.count == 1 ? "1 workspace is ready." : "\(model.pairedWorkspaces.count) workspaces are ready.")
                            .padding(.top, 28)
                    } else {
                        ScreenHeading(title: "Let's get connected.", subtitle: "Use your invitation to bring your workspaces along.").padding(.top, 28)
                    }
                    if model.phase == .notifyStep {
                        notificationStep
                    } else {
                        invitationStep
                    }
                    ModelMessage()
                }.padding(.horizontal, 25).padding(.vertical, 24)
                    .frame(minHeight: geometry.size.height, alignment: .center)
            }
        }
        .sheet(isPresented: $showLink) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Paste invitation link").font(.headline)
                Text("Invitation link").themeFont(12).foregroundStyle(Theme.muted)
                TextField("orch://pair?…", text: $link)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .keyboardType(.URL).textContentType(.URL).submitLabel(.continue).onSubmit { submitLink() }.padding(14).frame(minHeight: 48)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(linkError == nil ? Theme.borderStrong : Theme.danger))
                    .accessibilityLabel("Invitation link").accessibilityIdentifier("invite-field")
                    .onChange(of: link) { _, _ in linkError = nil }
                if let linkError {
                    Text("⚠︎ \(linkError)").themeFont(13).foregroundStyle(Theme.danger).accessibilityIdentifier("invite-error")
                }
                Button("Continue") { submitLink() }.buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("invite-continue")
                Button { showLink = false } label: { Text("Close") }.buttonStyle(WideButtonStyle(color: Theme.muted))
            }.padding(23).presentationDetents([.medium, .large]).presentationBackground(Theme.bg)
        }
        .sheet(isPresented: $showScanner) {
            QRScannerView { code in model.openInvite(code); showScanner = false }
        }
    }

    private func submitLink() {
                    let clean = link.trimmingCharacters(in: .whitespacesAndNewlines)
                    if clean.isEmpty { linkError = "Paste the link you were sent first. It starts with orch://."; return }
                    if (try? PairingLink(clean)) == nil {
                        linkError = "That link does not look right. Check you copied the whole link, or ask the person who invited you for a new one."
                        return
                    }
                    model.openInvite(clean); showLink = false
    }

    @ViewBuilder private var invitationStep: some View {
        switch model.inviteState {
        case .none:
            VStack(spacing: 10) {
                Button { showScanner = true } label: { Label("Scan invitation QR code", systemImage: "qrcode.viewfinder") }
                    .buttonStyle(PrimaryButtonStyle())
                Button {
                    if let value = UIPasteboard.general.string, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                       (try? PairingLink(value)) != nil {
                        model.openInvite(value)
                    } else { showLink = true }
                } label: { Text("Paste invitation link") }.buttonStyle(SecondaryButtonStyle())
                Text("Ask the person who invited you for a link or QR code.").themeFont(12)
                    .foregroundStyle(Theme.muted).frame(maxWidth: .infinity).padding(.top, 4)
                #if DEBUG
                Button { model.openSampleInvite() } label: { Text("Try a demo") }
                    .buttonStyle(WideButtonStyle(color: Theme.muted)).themeFont(12)
                    .accessibilityIdentifier("sample-invite")
                #endif
            }
        case .found(let host):
            VStack(alignment: .leading, spacing: 12) {
                Text("Your invitation is ready").themeFont(15, .semibold)
                Text("Server: \(host)").themeFont(13).foregroundStyle(Theme.muted)
                Text("You were invited to connect this phone.").themeFont(13).foregroundStyle(Theme.muted)
                DisclosureGroup { Text(host).themeFont(12).frame(maxWidth: .infinity, alignment: .leading) } label: {
                    Text("Connection details").frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).contentShape(Rectangle())
                }
                    .themeFont(12).foregroundStyle(Theme.muted)
            }.orchCard()
            Button("Connect this phone") {
                Task { await model.connect(phoneName: UIDevice.current.name) }
            }.buttonStyle(PrimaryButtonStyle())
        case .connecting:
            ProgressView("Connecting this phone…").frame(maxWidth: .infinity, minHeight: 80)
        }
    }

    private var notificationStep: some View {
        VStack(spacing: 18) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Know when you're needed.").themeFont(17, .semibold)
                Text("Get notified when your work needs an answer.")
                    .themeFont(13).foregroundStyle(Theme.muted)
                ForEach(model.pairedWorkspaces) { workspace in
                    Text(workspace.displayName).themeFont(14).padding(.vertical, 6)
                }
            }.orchCard()
            Button("Allow notifications") { finish(true) }.buttonStyle(PrimaryButtonStyle())
            Button { finish(false) } label: { Text("Not now") }.buttonStyle(WideButtonStyle(color: Theme.muted)).themeFont(15)
            if finishing { ProgressView() }
        }.disabled(finishing)
    }

    private func finish(_ allowed: Bool) {
        finishing = true
        Task { await model.finishSetup(allowNotifications: allowed); finishing = false }
    }
}
