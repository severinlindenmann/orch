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
                        notificationStep
                    } else {
                        ScreenHeading(title: "Let's get connected.", subtitle: "Bring your workspaces along with an invitation.").padding(.top, 28)
                        invitationStep
                    }
                    ModelMessage()
                }.padding(.horizontal, 25).padding(.vertical, 24)
                    .frame(minHeight: geometry.size.height, alignment: .center)
            }
        }
        .sheet(isPresented: $showLink) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Paste link").font(.headline)
                Text("Invitation link").themeFont(12).foregroundStyle(Theme.muted)
                TextField("orch://pair?…", text: $link)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .keyboardType(.URL).textContentType(.URL).submitLabel(.continue).onSubmit { submitLink() }.padding(14).frame(minHeight: 48)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).stroke(linkError == nil ? Theme.borderStrong : Theme.danger))
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
            QRScannerView(onPaste: { showScanner = false; showLink = true }) { code in model.openInvite(code); showScanner = false }
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
                Button { showScanner = true } label: { Label("Scan QR code", systemImage: "qrcode.viewfinder") }
                    .buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("invite-scan")
                Button { pasteLink() } label: { Text("Paste link") }.buttonStyle(SecondaryButtonStyle())
                    .accessibilityIdentifier("invite-paste")
                InviteHelp()
                #if DEBUG
                Button { model.openSampleInvite() } label: { Text("Try a demo").frame(maxWidth: .infinity, minHeight: 44).contentShape(Rectangle()) }
                    .buttonStyle(WideButtonStyle(color: Theme.muted)).themeFont(15)
                    .accessibilityIdentifier("sample-invite")
                #endif
            }
        case .found(let host):
            VStack(alignment: .leading, spacing: 12) {
                Text("Your invitation is ready").themeFont(15, .semibold)
                Text("You were invited to connect this phone.").themeFont(13).foregroundStyle(Theme.muted)
                DisclosureGroup { Text(host).themeFont(13).frame(maxWidth: .infinity, alignment: .leading) } label: {
                    Text("Connection details").frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).contentShape(Rectangle())
                }
                    .themeFont(13).foregroundStyle(Theme.muted)
            }.orchCard()
            if model.inviteNeedsReplacement {
                Button("Use a new invitation") { model.clearInvite() }.buttonStyle(PrimaryButtonStyle())
                    .accessibilityIdentifier("invite-new")
            } else {
                Button("Connect this phone") {
                    Task { await model.connect(phoneName: UIDevice.current.name) }
                }.buttonStyle(PrimaryButtonStyle())
                Button("Use a different link") { model.clearInvite() }.buttonStyle(WideButtonStyle(color: Theme.muted))
                    .accessibilityIdentifier("invite-different")
            }
        case .connecting:
            ProgressView("Connecting this phone…").frame(maxWidth: .infinity, minHeight: 80)
        }
    }

    private func pasteLink() {
        if let value = UIPasteboard.general.string, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           (try? PairingLink(value)) != nil {
            model.openInvite(value)
        } else { showLink = true }
    }

    private var notificationStep: some View {
        VStack(spacing: 18) {
            VStack(alignment: .leading, spacing: 12) {
                Image(systemName: "bell").foregroundStyle(Theme.brand)
                Text("Get told when something needs you").themeFont(17, .semibold)
                Text("Questions and finished work, straight to your phone.")
                    .themeFont(13).foregroundStyle(Theme.muted)

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

/// "Get an invitation": where the invitation comes from, with the computer-side steps behind a tap.
struct InviteHelp: View {
    @State private var open = false
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(InviteWording.source).themeFont(13).foregroundStyle(Theme.muted)
            Button { open.toggle() } label: {
                HStack {
                    Text(InviteWording.stepsTitle)
                    Image(systemName: open ? "chevron.up" : "chevron.down").themeFont(12).accessibilityHidden(true)
                }.themeFont(15).foregroundStyle(Theme.brand).frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).contentShape(Rectangle())
            }.buttonStyle(PressStyle()).accessibilityIdentifier("invite-help")
                .accessibilityValue(open ? "Shown" : "Hidden")
            if open {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(InviteWording.steps.enumerated()), id: \.offset) { index, step in
                        Text("\(index + 1). \(step)").themeFont(13).fixedSize(horizontal: false, vertical: true)
                    }
                }.foregroundStyle(Theme.text).accessibilityIdentifier("invite-help-steps")
            }
        }.frame(maxWidth: .infinity, alignment: .leading).padding(.top, 4)
    }
}
