Name:           platesmith
Version:        1.0.0
Release:        1%{?dist}
Summary:        Forge SVGs into multi-color Bambu Lab 3MF plates
License:        GPL-3.0-or-later
URL:            https://github.com/bkiu/platesmith
Source0:        platesmith-%{version}.tar.gz
Source1:        platesmith.service
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  systemd-rpm-macros
# for %%check
BuildRequires:  python3-pytest
BuildRequires:  python3-httpx

%description
Platesmith is a local web app that turns SVG files into multi-color 3MF
projects for Bambu Lab printers: design a rounded base plate, place and
resize SVG layers with individual colors and thicknesses, preview in 3D,
and export a Bambu Studio project with filament colors pre-assigned.

%prep
%autosetup -n platesmith-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files platesmith
install -D -m 0644 %{SOURCE1} %{buildroot}%{_userunitdir}/platesmith.service

%check
%pytest tests/

%files -f %{pyproject_files}
%doc README.md
%license LICENSE
%{_bindir}/platesmith
%{_userunitdir}/platesmith.service

%changelog
* Fri Jul 03 2026 Brendan Kiu <brendankiu@gfa.org> - 1.0.0-1
- Initial package
